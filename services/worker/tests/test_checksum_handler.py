import hashlib
import pytest
from unittest.mock import MagicMock, patch

from modules.checksum.handler import (
    ChecksumVerificationError,
    _local_sha256,
    verify_sftp,
    verify_rsync,
)


class TestLocalSha256:
    def test_returns_correct_hash(self, tmp_path):
        data = b"hello world"
        f = tmp_path / "test.bin"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert _local_sha256(str(f)) == expected

    def test_reads_large_file_correctly(self, tmp_path):
        data = b"x" * (65536 * 2 + 1)
        f = tmp_path / "large.bin"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert _local_sha256(str(f)) == expected


class TestVerifySftp:
    def _make_client(self, stdout_content: bytes, stderr_content: bytes = b"", exit_status: int = 0):
        mock_client = MagicMock()
        mock_chan = MagicMock()
        mock_chan.recv_exit_status.return_value = exit_status
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = stdout_content
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = stderr_content
        mock_client.exec_command.return_value = (mock_chan, mock_stdout, mock_stderr)
        return mock_client

    def test_ok_when_hashes_match(self, tmp_path):
        data = b"file content"
        src = tmp_path / "src.bin"
        src.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        client = self._make_client(f"{sha}  /dest/file.bin\n".encode())
        logs = []
        verify_sftp(str(src), client, "/dest/file.bin", lambda lvl, msg: logs.append(msg))
        assert any("SHA-256 OK" in m for m in logs)

    def test_raises_on_mismatch(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"local content")
        wrong_hash = "deadbeef" * 8  # 64 hex chars, inny niż lokalny
        client = self._make_client(f"{wrong_hash}  /dest/file.bin\n".encode())
        with pytest.raises(ChecksumVerificationError, match="MISMATCH"):
            verify_sftp(str(src), client, "/dest/file.bin", lambda lvl, msg: None)

    def test_raises_when_sha256sum_missing(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"content")
        client = self._make_client(b"", b"sha256sum: command not found", exit_status=1)
        with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
            verify_sftp(str(src), client, "/dest/file.bin", lambda lvl, msg: None)

    def test_raises_when_exit_status_nonzero(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"content")
        # sha256sum writes something to stdout but exit != 0 (e.g. read error)
        client = self._make_client(b"partial output", b"read error", exit_status=1)
        with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
            verify_sftp(str(src), client, "/dest/file.bin", lambda lvl, msg: None)


class TestVerifyRsync:
    def _make_result(self, returncode, stdout="", stderr=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_ok_when_hashes_match(self, tmp_path):
        data = b"file content"
        src = tmp_path / "src.bin"
        src.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        result = self._make_result(0, f"{sha}  /dest/file.bin\n")
        logs = []
        with patch("modules.checksum.handler.subprocess.run", return_value=result):
            verify_rsync(
                str(src), ["ssh", "user@host"], "/dest/file.bin",
                lambda lvl, msg: logs.append(msg),
            )
        assert any("SHA-256 OK" in m for m in logs)

    def test_raises_on_mismatch(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"local content")
        wrong_hash = "deadbeef" * 8
        result = self._make_result(0, f"{wrong_hash}  /dest/file.bin\n")
        with patch("modules.checksum.handler.subprocess.run", return_value=result):
            with pytest.raises(ChecksumVerificationError, match="MISMATCH"):
                verify_rsync(
                    str(src), ["ssh", "user@host"], "/dest/file.bin",
                    lambda lvl, msg: None,
                )

    def test_raises_on_nonzero_exit(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"content")
        result = self._make_result(1, "", "sha256sum: No such file or directory")
        with patch("modules.checksum.handler.subprocess.run", return_value=result):
            with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
                verify_rsync(
                    str(src), ["ssh", "user@host"], "/dest/file.bin",
                    lambda lvl, msg: None,
                )

    def test_raises_when_stdout_empty(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"content")
        result = self._make_result(0, "", "")  # returncode=0 but empty stdout
        with patch("modules.checksum.handler.subprocess.run", return_value=result):
            with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
                verify_rsync(
                    str(src), ["ssh", "user@host"], "/dest/file.bin",
                    lambda lvl, msg: None,
                )
