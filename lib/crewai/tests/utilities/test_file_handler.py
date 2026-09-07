import hashlib
import hmac
import os
import unittest
import uuid

import pytest
from crewai.utilities.file_handler import PickleHandler, PickleIntegrityError


class TestPickleHandler(unittest.TestCase):
    def setUp(self):
        # Use a unique file name for each test to avoid race conditions in parallel test execution
        unique_id = str(uuid.uuid4())
        self.file_name = f"test_data_{unique_id}.pkl"
        self.file_path = os.path.join(os.getcwd(), self.file_name)
        self.handler = PickleHandler(self.file_name)

    def tearDown(self):
        for path in (
            self.file_path,
            self.file_path + ".key",
            self.file_path + ".sig",
        ):
            if os.path.exists(path):
                os.remove(path)

    def test_initialize_file(self):
        assert os.path.exists(self.file_path) is False

        self.handler.initialize_file()

        assert os.path.exists(self.file_path) is True
        assert os.path.getsize(self.file_path) >= 0

    def test_save_and_load(self):
        data = {"key": "value"}
        self.handler.save(data)
        loaded_data = self.handler.load()
        assert loaded_data == data

    def test_load_empty_file(self):
        loaded_data = self.handler.load()
        assert loaded_data == {}

    def test_load_corrupted_file_with_valid_signature_raises_unpickling_error(self):
        """A file that passes integrity verification but isn't valid pickle
        data still surfaces the underlying unpickling error -- the integrity
        check only gates *whether* to attempt unpickling, not the outcome of
        doing so."""
        # Go through save() once to establish a real signing key, then
        # overwrite the payload (but not the signature) with corrupted bytes
        # signed under that same key, so the integrity check passes and the
        # corruption is what actually surfaces.
        self.handler.save({"key": "value"})
        corrupted = b"corrupted data"
        key = self.handler._load_or_create_signing_key()

        with open(self.file_path, "wb") as file:
            file.write(corrupted)
            file.flush()
            os.fsync(file.fileno())
        with open(self.file_path + ".sig", "wb") as file:
            file.write(hmac.new(key, corrupted, hashlib.sha256).digest())

        with pytest.raises(Exception) as exc:
            self.handler.load()

        assert str(exc.value) == "pickle data was truncated"
        assert "<class '_pickle.UnpicklingError'>" == str(exc.type)

    def test_load_refuses_file_with_no_signature(self):
        """Regression test for the confirmed Low-severity finding: a .pkl
        file with no accompanying .key/.sig (e.g. written by something other
        than this handler, or copied in from elsewhere) must be refused
        rather than unpickled unconditionally -- pickle.load() on untrusted
        data can execute arbitrary code."""
        with open(self.file_path, "wb") as file:
            file.write(b"anything at all")
            file.flush()
            os.fsync(file.fileno())

        with pytest.raises(PickleIntegrityError, match="no integrity signature"):
            self.handler.load()

    def test_load_refuses_file_with_tampered_signature(self):
        """A payload that doesn't match its recorded signature (modified or
        replaced since it was last saved) must be refused, not silently
        unpickled."""
        self.handler.save({"key": "value"})

        with open(self.handler._sig_path, "wb") as file:
            file.write(b"\x00" * 32)  # a syntactically valid, wrong signature

        with pytest.raises(PickleIntegrityError, match="does not match"):
            self.handler.load()

    def test_save_then_load_round_trips_on_the_same_machine(self):
        """The core non-regression: normal same-process save-then-load must
        keep working unchanged now that every save is signed."""
        data = {"nested": {"list": [1, 2, 3]}, "value": "ok"}
        self.handler.save(data)

        assert self.handler.load() == data

    def test_signing_key_file_has_owner_only_permissions(self):
        """The signing key is local-trust material, not a secret meant to
        resist a same-machine attacker, but it should still default to
        owner-only permissions rather than being world-readable."""
        self.handler.save({"key": "value"})

        mode = os.stat(self.handler._key_path).st_mode & 0o777
        assert mode == 0o600
