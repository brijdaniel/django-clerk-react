"""
Tests for storage provider abstraction.

Tests:
- StorageProvider base class (validation, filename generation)
- MockStorageProvider implementation
- Provider factory function
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError

from app.utils.storage import MockStorageProvider, StorageProvider, _StorageCache, get_storage_provider


class TestStorageProviderValidation:
    """Tests for StorageProvider file validation."""

    def test_validate_file_accepts_image_png(self):
        """PNG images accepted."""
        provider = MockStorageProvider()
        image = SimpleUploadedFile('test.png', b'image', content_type='image/png')
        provider._validate_file(image, 'image/png')  # Should not raise

    def test_validate_file_accepts_image_jpeg(self):
        """JPEG images accepted."""
        provider = MockStorageProvider()
        image = SimpleUploadedFile('test.jpg', b'image', content_type='image/jpeg')
        provider._validate_file(image, 'image/jpeg')  # Should not raise

    def test_validate_file_accepts_image_gif(self):
        """GIF images accepted."""
        provider = MockStorageProvider()
        image = SimpleUploadedFile('test.gif', b'image', content_type='image/gif')
        provider._validate_file(image, 'image/gif')  # Should not raise

    def test_validate_file_rejects_text(self):
        """Text files rejected."""
        provider = MockStorageProvider()
        txt = SimpleUploadedFile('test.txt', b'text', content_type='text/plain')

        with pytest.raises(ValidationError) as exc_info:
            provider._validate_file(txt, 'text/plain')
        assert 'image' in str(exc_info.value).lower()

    def test_validate_file_rejects_pdf(self):
        """PDF files rejected."""
        provider = MockStorageProvider()
        pdf = SimpleUploadedFile('test.pdf', b'pdf', content_type='application/pdf')

        with pytest.raises(ValidationError):
            provider._validate_file(pdf, 'application/pdf')

    def test_validate_file_rejects_oversized(self):
        """Files exceeding MAX_FILE_SIZE rejected."""
        provider = MockStorageProvider()
        large = SimpleUploadedFile(
            'large.png',
            b'x' * (StorageProvider.MAX_FILE_SIZE + 1),
            content_type='image/png'
        )

        with pytest.raises(ValidationError) as exc_info:
            provider._validate_file(large, 'image/png')
        assert 'File too large' in str(exc_info.value)

    def test_validate_file_accepts_at_limit(self):
        """Files exactly at MAX_FILE_SIZE accepted."""
        provider = MockStorageProvider()
        at_limit = SimpleUploadedFile(
            'limit.png',
            b'x' * StorageProvider.MAX_FILE_SIZE,
            content_type='image/png'
        )
        provider._validate_file(at_limit, 'image/png')  # Should not raise


class TestStorageProviderFilenameGeneration:
    """Tests for filename generation."""

    def test_generate_unique_filename_preserves_extension(self):
        """Generated filename preserves original extension."""
        provider = MockStorageProvider()

        filename = provider._generate_unique_filename('photo.jpg')
        assert filename.endswith('.jpg')

        filename = provider._generate_unique_filename('image.png')
        assert filename.endswith('.png')

    def test_generate_unique_filename_is_unique(self):
        """Generated filenames are unique."""
        provider = MockStorageProvider()

        filename1 = provider._generate_unique_filename('test.jpg')
        filename2 = provider._generate_unique_filename('test.jpg')

        assert filename1 != filename2

    def test_generate_unique_filename_format(self):
        """Generated filename has expected format (UUID.ext)."""
        provider = MockStorageProvider()
        filename = provider._generate_unique_filename('photo.jpg')

        # Should be 16-char hex UUID + .jpg (4 chars) = 20 chars
        assert len(filename) == 20
        assert filename.endswith('.jpg')


class TestMockStorageProvider:
    """Tests for MockStorageProvider implementation."""

    def test_upload_file_returns_success(self):
        """upload_file returns success with mock URL."""
        provider = MockStorageProvider()
        image = SimpleUploadedFile('test.jpg', b'image', content_type='image/jpeg')

        result = provider.upload_file(image, 'test.jpg', 'image/jpeg')

        assert result['success'] is True
        assert result['url'].startswith('https://mock-storage.example.com/')
        assert result['file_id'] is not None
        assert result['error'] is None
        assert result['size'] == len(b'image')
        assert result['content_type'] == 'image/jpeg'

    def test_upload_file_validates_type(self):
        """upload_file validates file type."""
        provider = MockStorageProvider()
        txt = SimpleUploadedFile('test.txt', b'text', content_type='text/plain')

        with pytest.raises(ValidationError) as exc_info:
            provider.upload_file(txt, 'test.txt', 'text/plain')

        assert 'image' in str(exc_info.value).lower()

    def test_upload_file_validates_size(self):
        """upload_file validates file size."""
        provider = MockStorageProvider()
        large = SimpleUploadedFile(
            'large.jpg',
            b'x' * (StorageProvider.MAX_FILE_SIZE + 1),
            content_type='image/jpeg'
        )

        with pytest.raises(ValidationError) as exc_info:
            provider.upload_file(large, 'large.jpg', 'image/jpeg')

        assert 'File too large' in str(exc_info.value)

    def test_upload_file_generates_unique_filename(self):
        """upload_file generates unique file_id."""
        provider = MockStorageProvider()
        image1 = SimpleUploadedFile('test.jpg', b'image1', content_type='image/jpeg')
        image2 = SimpleUploadedFile('test.jpg', b'image2', content_type='image/jpeg')

        result1 = provider.upload_file(image1, 'test.jpg', 'image/jpeg')
        result2 = provider.upload_file(image2, 'test.jpg', 'image/jpeg')

        assert result1['file_id'] != result2['file_id']

    def test_upload_file_url_includes_file_id(self):
        """upload_file URL includes generated file_id."""
        provider = MockStorageProvider()
        image = SimpleUploadedFile('test.jpg', b'image', content_type='image/jpeg')

        result = provider.upload_file(image, 'test.jpg', 'image/jpeg')

        assert result['file_id'] in result['url']


class TestGetStorageProvider:
    """Tests for get_storage_provider factory function."""

    def setup_method(self):
        self._original = _StorageCache.instance
        _StorageCache.instance = None

    def teardown_method(self):
        _StorageCache.instance = self._original

    def test_returns_configured_provider(self, settings):
        """get_storage_provider returns configured provider class."""
        settings.STORAGE_PROVIDER_CLASS = 'app.utils.storage.MockStorageProvider'
        settings.STORAGE_PROVIDER_CONFIG = {}
        provider = get_storage_provider()
        assert isinstance(provider, StorageProvider)

    def test_returns_singleton(self, settings):
        """get_storage_provider returns same instance on multiple calls."""
        settings.STORAGE_PROVIDER_CLASS = 'app.utils.storage.MockStorageProvider'
        settings.STORAGE_PROVIDER_CONFIG = {}
        provider1 = get_storage_provider()
        provider2 = get_storage_provider()
        assert provider1 is provider2
