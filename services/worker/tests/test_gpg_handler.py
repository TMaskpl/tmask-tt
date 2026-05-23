# services/worker/tests/test_gpg_handler.py
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.gpg.handler import encrypt_file, GPGEncryptError


class TestEncryptFile:
    def _make_source(self, content=b'secret data'):
        fd, path = tempfile.mkstemp()
        os.write(fd, content)
        os.close(fd)
        return path

    def test_returns_path_on_success(self):
        source = self._make_source()
        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            with patch('modules.gpg.handler.subprocess.run', return_value=mock_result):
                with patch('builtins.open', MagicMock()):
                    encrypted = encrypt_file(source, 'secret123')
            assert encrypted.endswith('.gpg')
            assert os.path.exists(encrypted)
        finally:
            os.unlink(source)
            if os.path.exists(encrypted):
                os.unlink(encrypted)

    def test_raises_on_gpg_failure(self):
        source = self._make_source()
        try:
            mock_result = MagicMock()
            mock_result.returncode = 2
            mock_result.stderr = 'gpg: invalid passphrase'
            with patch('modules.gpg.handler.subprocess.run', return_value=mock_result):
                with pytest.raises(GPGEncryptError, match='GPG FAILED'):
                    encrypt_file(source, 'wrong')
        finally:
            os.unlink(source)

    def test_raises_when_gpg_not_installed(self):
        source = self._make_source()
        try:
            with patch('modules.gpg.handler.subprocess.run', side_effect=FileNotFoundError):
                with pytest.raises(GPGEncryptError, match='GPG NOT INSTALLED'):
                    encrypt_file(source, 'secret123')
        finally:
            os.unlink(source)

    def test_cleans_up_temp_file_on_failure(self):
        source = self._make_source()
        captured = {}

        original_mkstemp = tempfile.mkstemp

        def mock_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            captured['path'] = path
            return fd, path

        try:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = 'error'
            with patch('modules.gpg.handler.subprocess.run', return_value=mock_result), \
                 patch('modules.gpg.handler.tempfile.mkstemp', side_effect=mock_mkstemp):
                with pytest.raises(GPGEncryptError):
                    encrypt_file(source, 'secret')
            assert not os.path.exists(captured['path'])
        finally:
            os.unlink(source)
