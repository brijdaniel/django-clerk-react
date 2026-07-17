import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, cast
from urllib.parse import urlparse

from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)
from django.conf import settings
from rest_framework.exceptions import ValidationError


logger = logging.getLogger(__name__)


class StorageProvider(ABC):
    """Abstract base class for media storage providers.

    Handles file validation and filename generation in the base class, so concrete
    implementations only need to focus on the actual storage logic.

    All public methods handle validation automatically before calling the abstract
    implementation methods.
    """

    def __init__(self, **kwargs):
        pass

    ALLOWED_TYPES = {'image/png', 'image/jpeg', 'image/jpg', 'image/gif'}
    MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB

    def _validate_file(self, file_obj, content_type: str) -> None:
        """Validate file before storage. Raises ValidationError on failure."""
        if not file_obj:
            raise ValidationError('No file provided.')

        if content_type.lower() not in self.ALLOWED_TYPES:
            allowed = ', '.join(sorted(self.ALLOWED_TYPES))
            raise ValidationError(f'Invalid file type. Allowed: {allowed}')

        if file_obj.size > self.MAX_FILE_SIZE:
            max_mb = self.MAX_FILE_SIZE // (1024 * 1024)
            raise ValidationError(f'File too large. Maximum size: {max_mb}MB')

    def _generate_unique_filename(self, original_filename: str) -> str:
        """Generate UUID-based filename preserving extension."""
        ext = Path(original_filename).suffix.lower()  # e.g., '.png'
        unique_id = uuid.uuid4().hex[:16]
        return f"{unique_id}{ext}"

    def upload_file(self, file_obj, filename: str, content_type: str) -> dict:
        """Upload a file to storage.

        Validates the file, generates a unique filename, then calls _upload_file_impl().

        Args:
            file_obj: Django UploadedFile object
            filename: Original filename from upload
            content_type: MIME type of the file

        Returns:
            dict with keys: success (bool), url (str), file_id (str), error (str),
            size (int), content_type (str)
        """
        # Validate file
        self._validate_file(file_obj, content_type)

        # Generate unique filename
        unique_filename = self._generate_unique_filename(filename)

        # Call implementation
        result = self._upload_file_impl(file_obj, unique_filename, content_type)
        result['file_id'] = unique_filename
        result['size'] = file_obj.size
        result['content_type'] = content_type
        return result

    @abstractmethod
    def _upload_file_impl(self, file_obj, unique_filename: str, content_type: str) -> dict:
        """Implementation method for uploading files.

        File is already validated and filename is unique.

        Args:
            file_obj: Django UploadedFile object
            unique_filename: Unique filename (UUID-based with extension)
            content_type: MIME type

        Returns:
            dict with keys: success (bool), url (str), error (str)
        """
        pass

    @abstractmethod
    def delete_blob(self, blob_name: str) -> bool:
        """Delete a blob from storage.

        Args:
            blob_name: The blob filename to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        pass

    @staticmethod
    def extract_blob_name(url: str) -> Optional[str]:
        """Extract the blob filename from a storage URL.

        Parses the last path segment from the URL, stripping query params.
        Works for both Azure and mock URLs.
        """
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        return path.split('/')[-1] if path else None


class MockStorageProvider(StorageProvider):
    """Mock storage provider for development and testing.

    Logs all operations but doesn't actually store files.
    Always returns success with generated URLs.
    """

    def _upload_file_impl(self, file_obj, unique_filename: str, content_type: str) -> dict:
        """Log upload and return mock URL."""
        mock_url = f'https://mock-storage.example.com/media/{unique_filename}'

        logger.info(
            'MockStorageProvider.upload_file',
            extra={
                'blob_name': unique_filename,
                'content_type': content_type,
                'size': file_obj.size,
                'url': mock_url,
            },
        )

        return {
            'success': True,
            'url': mock_url,
            'error': None,
        }

    def delete_blob(self, blob_name: str) -> bool:
        """Log deletion and return success."""
        logger.info('MockStorageProvider.delete_blob', extra={'blob_name': blob_name})
        return True


class AzureBlobStorageProvider(StorageProvider):
    """Azure Blob Storage provider.

    Uses azure-storage-blob SDK to upload files to Azure Blob Storage.
    Authenticates with account name + key to enable per-blob SAS token generation.
    """

    SAS_EXPIRY_HOURS = 1

    def __init__(self, account_name: str = '', account_key: str = '', container: str = 'media'):
        """Initialize Azure Blob Storage provider.

        Args:
            account_name: Azure Storage account name
            account_key: Azure Storage account key
            container: Container name (default: 'media')

        Raises:
            ValueError: If account_name or account_key is not provided
        """
        if not account_name or not account_key:
            raise ValueError(
                'Azure Blob Storage account_name and account_key are required. '
                'Set AZURE_STORAGE_ACCOUNT_NAME and AZURE_STORAGE_ACCOUNT_KEY environment variables.'
            )

        self.account_name = account_name
        self.account_key = account_key
        self.container = container

        account_url = f'https://{account_name}.blob.core.windows.net'
        credential = AzureNamedKeyCredential(account_name, account_key)
        self.blob_service_client = BlobServiceClient(
            account_url=account_url,
            credential=credential,
        )

        self._ensure_container_exists()

        logger.info(
            f'AzureBlobStorageProvider initialized with container: {container}'
        )

    def _ensure_container_exists(self):
        """Create the blob container if it doesn't already exist."""
        try:
            container_client = self.blob_service_client.get_container_client(self.container)
            container_client.get_container_properties()
        except ResourceNotFoundError:
            try:
                self.blob_service_client.create_container(self.container)
                logger.info(f'Created Azure Blob Storage container: {self.container}')
            except AzureError as e:
                logger.warning(
                    f'Could not create container {self.container}: {e}',
                    exc_info=True,
                )

    def _generate_sas_url(self, blob_name: str) -> str:
        """Generate a short-lived, read-only SAS URL for a specific blob."""
        sas_token = generate_blob_sas(
            account_name=self.account_name,
            container_name=self.container,
            blob_name=blob_name,
            account_key=self.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=self.SAS_EXPIRY_HOURS),
        )
        return (
            f'https://{self.account_name}.blob.core.windows.net'
            f'/{self.container}/{blob_name}?{sas_token}'
        )

    def _upload_file_impl(self, file_obj, unique_filename: str, content_type: str) -> dict:
        """Upload file to Azure Blob Storage and return a short-lived SAS URL."""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container,
                blob=unique_filename
            )

            blob_client.upload_blob(
                file_obj.read(),
                content_settings=ContentSettings(content_type=content_type),
                overwrite=False
            )

            url = self._generate_sas_url(unique_filename)

            logger.info(
                'AzureBlobStorageProvider.upload_file',
                extra={
                    'blob_name': unique_filename,
                    'content_type': content_type,
                    'size': file_obj.size,
                },
            )

            return {
                'success': True,
                'url': url,
                'error': None,
            }

        except AzureError as e:
            error_msg = f'Azure Blob Storage upload failed: {str(e)}'
            logger.error(
                'AzureBlobStorageProvider.upload_file failed',
                extra={
                    'blob_name': unique_filename,
                    'error': error_msg,
                },
                exc_info=True,
            )

            return {
                'success': False,
                'url': None,
                'error': error_msg,
            }

    def delete_blob(self, blob_name: str) -> bool:
        """Delete a blob from Azure Blob Storage."""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container,
                blob=blob_name,
            )
            blob_client.delete_blob()
            logger.info('AzureBlobStorageProvider.delete_blob', extra={'blob_name': blob_name})
            return True
        except AzureError as e:
            logger.warning(
                f'Failed to delete blob {blob_name}: {e}',
                exc_info=True,
            )
            return False


class _StorageCache:
    """Simple cache for the storage provider singleton."""
    instance: Optional[StorageProvider] = None


def get_storage_provider() -> StorageProvider:
    """Get the configured storage provider instance (singleton).

    Provider class is determined by settings.STORAGE_PROVIDER_CLASS.
    Configuration is passed from settings.STORAGE_PROVIDER_CONFIG.
    Instance is cached in _StorageCache.
    """
    if _StorageCache.instance is None:
        provider_path = getattr(
            settings,
            'STORAGE_PROVIDER_CLASS',
            'app.utils.storage.MockStorageProvider'
        )

        # Import the provider class
        module_path, class_name = provider_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)

        # Get provider configuration
        config = getattr(settings, 'STORAGE_PROVIDER_CONFIG', {})

        # Instantiate with config
        _StorageCache.instance = provider_class(**config)
        logger.info(f'Initialised storage provider: {provider_path}')

    return cast(StorageProvider, _StorageCache.instance)
