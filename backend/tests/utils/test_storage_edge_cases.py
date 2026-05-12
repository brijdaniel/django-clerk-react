"""
Additional tests for storage providers to achieve 100% coverage.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from azure.core.exceptions import AzureError, ResourceNotFoundError
from rest_framework.exceptions import ValidationError

from app.utils.storage import (
    MockStorageProvider,
    AzureBlobStorageProvider,
    StorageProvider,
)


class TestStorageProviderValidation:
    """Test StorageProvider validation methods."""

    def test_validate_file_no_file_provided(self):
        """Raises ValidationError when no file provided."""
        provider = MockStorageProvider()

        with pytest.raises(ValidationError) as exc_info:
            provider._validate_file(None, 'image/png')

        assert 'No file provided' in str(exc_info.value.detail)

    def test_validate_file_invalid_type(self):
        """Raises ValidationError for invalid file type."""
        provider = MockStorageProvider()
        file_obj = Mock()
        file_obj.size = 1000

        with pytest.raises(ValidationError) as exc_info:
            provider._validate_file(file_obj, 'application/pdf')

        assert 'Invalid file type' in str(exc_info.value.detail)

    def test_validate_file_case_insensitive_type(self):
        """Validates file type case-insensitively."""
        provider = MockStorageProvider()
        file_obj = Mock()
        file_obj.size = 1000

        # Should not raise for uppercase
        provider._validate_file(file_obj, 'IMAGE/PNG')

    def test_validate_file_too_large(self):
        """Raises ValidationError for files exceeding size limit."""
        provider = MockStorageProvider()
        file_obj = Mock()
        file_obj.size = StorageProvider.MAX_FILE_SIZE + 1

        with pytest.raises(ValidationError) as exc_info:
            provider._validate_file(file_obj, 'image/png')

        assert 'File too large' in str(exc_info.value.detail)


class TestExtractBlobName:
    """Test StorageProvider.extract_blob_name static method."""

    def test_extracts_from_azure_url(self):
        url = 'https://myaccount.blob.core.windows.net/media/abc123.png?sv=2022&sig=xyz'
        assert StorageProvider.extract_blob_name(url) == 'abc123.png'

    def test_extracts_from_mock_url(self):
        url = 'https://mock-storage.example.com/media/abc123.png'
        assert StorageProvider.extract_blob_name(url) == 'abc123.png'

    def test_returns_none_for_empty_path(self):
        assert StorageProvider.extract_blob_name('https://example.com') is None

    def test_returns_none_for_empty_string(self):
        assert StorageProvider.extract_blob_name('') is None


class TestMockStorageProviderDeleteBlob:
    """Test MockStorageProvider.delete_blob."""

    def test_delete_blob_returns_true(self):
        provider = MockStorageProvider()
        assert provider.delete_blob('abc123.png') is True


# ---------------------------------------------------------------------------
# Azure provider helpers
# ---------------------------------------------------------------------------

def _create_provider(account_name='testaccount', account_key='testkey', container='media'):
    """Create an AzureBlobStorageProvider with mocked Azure SDK."""
    mock_blob_service = Mock()
    with patch('app.utils.storage.BlobServiceClient', return_value=mock_blob_service) as mock_cls, \
         patch('app.utils.storage.AzureNamedKeyCredential') as mock_cred:
        provider = AzureBlobStorageProvider(
            account_name=account_name,
            account_key=account_key,
            container=container,
        )
    return provider, mock_blob_service


class TestAzureBlobStorageProvider:
    """Test AzureBlobStorageProvider initialization and upload."""

    def test_init_without_account_name(self):
        """Raises ValueError when account_name not provided."""
        with pytest.raises(ValueError) as exc_info:
            AzureBlobStorageProvider(account_name='', account_key='key')

        assert 'account_name and account_key are required' in str(exc_info.value)

    def test_init_without_account_key(self):
        """Raises ValueError when account_key not provided."""
        with pytest.raises(ValueError) as exc_info:
            AzureBlobStorageProvider(account_name='name', account_key='')

        assert 'account_name and account_key are required' in str(exc_info.value)

    def test_init_constructs_account_url(self):
        """Constructs BlobServiceClient with account URL and credential."""
        with patch('app.utils.storage.BlobServiceClient') as mock_cls, \
             patch('app.utils.storage.AzureNamedKeyCredential') as mock_cred:
            mock_cls.return_value = Mock()
            AzureBlobStorageProvider(account_name='testaccount', account_key='testkey')

            mock_cred.assert_called_once_with('testaccount', 'testkey')
            mock_cls.assert_called_once_with(
                account_url='https://testaccount.blob.core.windows.net',
                credential=mock_cred.return_value,
            )

    def test_upload_file_returns_sas_url(self):
        """Upload returns a URL with per-blob SAS token."""
        provider, mock_blob_service = _create_provider()

        mock_blob_client = Mock()
        mock_blob_service.get_blob_client.return_value = mock_blob_client

        file_obj = Mock()
        file_obj.read.return_value = b'fake image data'
        file_obj.size = 1000

        with patch('app.utils.storage.generate_blob_sas', return_value='sv=2022&sig=fakesastoken'):
            result = provider._upload_file_impl(file_obj, 'abc123.png', 'image/png')

        assert result['success'] is True
        assert 'abc123.png' in result['url']
        assert 'sv=2022&sig=fakesastoken' in result['url']
        assert result['url'].startswith('https://testaccount.blob.core.windows.net/media/abc123.png?')
        assert result['error'] is None

    def test_upload_file_calls_generate_blob_sas(self):
        """Upload calls generate_blob_sas with correct params."""
        provider, mock_blob_service = _create_provider()

        mock_blob_client = Mock()
        mock_blob_service.get_blob_client.return_value = mock_blob_client

        file_obj = Mock()
        file_obj.read.return_value = b'data'
        file_obj.size = 4

        with patch('app.utils.storage.generate_blob_sas', return_value='token') as mock_gen:
            provider._upload_file_impl(file_obj, 'test.png', 'image/png')

            mock_gen.assert_called_once()
            call_kwargs = mock_gen.call_args[1]
            assert call_kwargs['account_name'] == 'testaccount'
            assert call_kwargs['container_name'] == 'media'
            assert call_kwargs['blob_name'] == 'test.png'
            assert call_kwargs['account_key'] == 'testkey'

    def test_upload_file_failure(self):
        """Tests upload failure handling."""
        provider, mock_blob_service = _create_provider()

        mock_blob_client = Mock()
        mock_blob_client.upload_blob.side_effect = AzureError('Azure error')
        mock_blob_service.get_blob_client.return_value = mock_blob_client

        file_obj = Mock()
        file_obj.read.return_value = b'fake image data'
        file_obj.size = 1000

        result = provider._upload_file_impl(file_obj, 'abc123.png', 'image/png')

        assert result['success'] is False
        assert result['url'] is None
        assert 'Azure Blob Storage upload failed' in result['error']
        assert 'Azure error' in result['error']


class TestEnsureContainerExists:
    """Test _ensure_container_exists auto-creates missing containers."""

    def test_container_exists_no_creation(self):
        """Does not create container when it already exists."""
        provider, mock_blob_service = _create_provider()

        mock_container_client = Mock()
        mock_blob_service.get_container_client.return_value = mock_container_client

        # Reset call counts from __init__
        mock_blob_service.get_container_client.reset_mock()
        mock_blob_service.create_container.reset_mock()

        provider._ensure_container_exists()

        mock_blob_service.get_container_client.assert_called_once_with('media')
        mock_container_client.get_container_properties.assert_called_once()
        mock_blob_service.create_container.assert_not_called()

    def test_container_missing_creates_it(self):
        """Creates container when get_container_properties raises."""
        provider, mock_blob_service = _create_provider()

        mock_container_client = Mock()
        mock_container_client.get_container_properties.side_effect = ResourceNotFoundError('ContainerNotFound')
        mock_blob_service.get_container_client.return_value = mock_container_client

        mock_blob_service.create_container.reset_mock()
        provider._ensure_container_exists()

        mock_blob_service.create_container.assert_called_once_with('media')

    def test_container_creation_failure_logs_warning(self):
        """Logs warning when container creation fails."""
        provider, mock_blob_service = _create_provider()

        mock_container_client = Mock()
        mock_container_client.get_container_properties.side_effect = ResourceNotFoundError('ContainerNotFound')
        mock_blob_service.get_container_client.return_value = mock_container_client
        mock_blob_service.create_container.side_effect = AzureError('AuthorizationFailure')

        with patch('app.utils.storage.logger') as mock_logger:
            provider._ensure_container_exists()
            mock_logger.warning.assert_called_once()
            assert 'media' in mock_logger.warning.call_args[0][0]

    def test_custom_container_name(self):
        """Uses custom container name when provided."""
        provider, mock_blob_service = _create_provider(container='custom-bucket')

        mock_container_client = Mock()
        mock_container_client.get_container_properties.side_effect = ResourceNotFoundError('ContainerNotFound')
        mock_blob_service.get_container_client.return_value = mock_container_client

        mock_blob_service.create_container.reset_mock()
        provider._ensure_container_exists()

        mock_blob_service.get_container_client.assert_called_with('custom-bucket')
        mock_blob_service.create_container.assert_called_once_with('custom-bucket')


class TestAzureDeleteBlob:
    """Test AzureBlobStorageProvider.delete_blob."""

    def test_delete_blob_success(self):
        """Deletes blob and returns True."""
        provider, mock_blob_service = _create_provider()

        mock_blob_client = Mock()
        mock_blob_service.get_blob_client.return_value = mock_blob_client

        result = provider.delete_blob('abc123.png')

        assert result is True
        mock_blob_service.get_blob_client.assert_called_with(
            container='media', blob='abc123.png',
        )
        mock_blob_client.delete_blob.assert_called_once()

    def test_delete_blob_failure_returns_false(self):
        """Returns False and logs warning when deletion fails."""
        provider, mock_blob_service = _create_provider()

        mock_blob_client = Mock()
        mock_blob_client.delete_blob.side_effect = AzureError('BlobNotFound')
        mock_blob_service.get_blob_client.return_value = mock_blob_client

        with patch('app.utils.storage.logger') as mock_logger:
            result = provider.delete_blob('abc123.png')

            assert result is False
            mock_logger.warning.assert_called_once()
