from datetime import datetime
import hashlib
import hmac
import json
import os
import pickle
import secrets
from typing import Any, TypedDict

from crewai_core.lock_store import lock as store_lock
from typing_extensions import Unpack


class LogEntry(TypedDict, total=False):
    """TypedDict for log entry kwargs with optional fields for flexibility."""

    task_name: str
    task: str
    agent: str
    status: str
    output: str
    input: str
    message: str
    level: str
    crew: str
    flow: str
    tool: str
    error: str
    duration: float
    metadata: dict[str, Any]


class FileHandler:
    """Handler for file operations supporting both JSON and text-based logging.

    Attributes:
        _path: The path to the log file.
    """

    def __init__(self, file_path: bool | str) -> None:
        """Initialize the FileHandler with the specified file path.
        Args:
            file_path: Path to the log file or boolean flag.
        """
        self._initialize_path(file_path)

    def _initialize_path(self, file_path: bool | str) -> None:
        """Initialize the file path based on the input type.

        Args:
            file_path: Path to the log file or boolean flag.

        Raises:
            ValueError: If file_path is neither a string nor a boolean.
        """
        if file_path is True:
            self._path = os.path.join(os.curdir, "logs.txt")

        elif isinstance(file_path, str):
            if file_path.endswith((".json", ".txt")):
                self._path = file_path
            else:
                self._path = file_path + ".txt"

        else:
            raise ValueError("file_path must be a string or boolean.")

    def log(self, **kwargs: Unpack[LogEntry]) -> None:
        """Log data with structured fields.

        Keyword Args:
            task_name: Name of the task.
            task: Description of the task.
            agent: Name of the agent.
            status: Status of the operation.
            output: Output data.
            input: Input data.
            message: Log message.
            level: Log level (e.g., INFO, ERROR).
            crew: Name of the crew.
            flow: Name of the flow.
            tool: Name of the tool used.
            error: Error message if any.
            duration: Duration of the operation in seconds.
            metadata: Additional metadata as a dictionary.

        Raises:
            ValueError: If logging fails.
        """
        try:
            with store_lock(f"file:{os.path.realpath(self._path)}"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_entry = {"timestamp": now, **kwargs}

                if self._path.endswith(".json"):
                    try:
                        with open(self._path, encoding="utf-8") as read_file:
                            existing_data = json.load(read_file)
                            existing_data.append(log_entry)
                    except (json.JSONDecodeError, FileNotFoundError):
                        existing_data = [log_entry]

                    with open(self._path, "w", encoding="utf-8") as write_file:
                        json.dump(existing_data, write_file, indent=4)
                        write_file.write("\n")

                else:
                    message = (
                        f"{now}: "
                        + ", ".join(
                            [f'{key}="{value}"' for key, value in kwargs.items()]
                        )
                        + "\n"
                    )
                    with open(self._path, "a", encoding="utf-8") as file:
                        file.write(message)

        except Exception as e:
            raise ValueError(f"Failed to log message: {e!s}") from e


class PickleIntegrityError(Exception):
    """Raised when a pickle file's integrity signature is missing or invalid.

    `PickleHandler.load()` will not unpickle data it cannot verify was
    written by this same handler -- an unauthenticated `pickle.load()` on a
    file that could plausibly come from outside this process's own writes
    (e.g. a shared or downloaded crew-training checkpoint) is an RCE vector,
    since unpickling can execute arbitrary code embedded in the payload.
    """


class PickleHandler:
    """Handler for saving and loading data using pickle.

    Every save is accompanied by an HMAC-SHA256 signature (stored in a
    sibling ``.sig`` file, keyed by a sibling ``.key`` file generated on
    first use) so that `load()` can refuse a file it did not itself sign,
    rather than unpickling untrusted data unconditionally. This does not
    protect against a same-machine attacker who can already read/write
    arbitrary files as this user -- its purpose is to distinguish a file
    this process actually wrote from one that arrived from somewhere else
    (a `.pkl` copied in from another machine or downloaded from a shared
    source), which the file's contents alone cannot reveal.

    Attributes:
        file_path: The path to the pickle file.
    """

    _SIGNATURE_KEY_SIZE = 32  # bytes; matches the SHA-256 output/key size used below.

    def __init__(self, file_name: str) -> None:
        """Initialize the PickleHandler with the name of the file where data will be stored.

        The file will be saved in the current directory.

        Args:
            file_name: The name of the file for saving and loading data.
        """
        if not file_name.endswith(".pkl"):
            file_name += ".pkl"

        self.file_path = os.path.join(os.getcwd(), file_name)
        self._key_path = self.file_path + ".key"
        self._sig_path = self.file_path + ".sig"

    def initialize_file(self) -> None:
        """Initialize the file with an empty dictionary and overwrite any existing data."""
        self.save({})

    def _load_or_create_signing_key(self) -> bytes:
        """Return this file's local HMAC signing key, generating one on first use.

        The key never leaves this machine and is stored with owner-only
        permissions; it exists only so `load()` can tell "written by this
        handler" apart from "arrived from elsewhere", not to resist a
        same-machine attacker who can already read files as this user.
        """
        try:
            with open(self._key_path, "rb") as f:
                key = f.read()
            if len(key) == self._SIGNATURE_KEY_SIZE:
                return key
        except FileNotFoundError:
            pass

        key = secrets.token_bytes(self._SIGNATURE_KEY_SIZE)
        fd = os.open(self._key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key

    def save(self, data: Any) -> None:
        """
        Save the data to the specified file using pickle, and write an
        accompanying HMAC-SHA256 integrity signature alongside it.

        Args:
          data: The data to be saved to the file.
        """
        with store_lock(f"file:{os.path.realpath(self.file_path)}"):
            key = self._load_or_create_signing_key()
            payload = pickle.dumps(data)
            signature = hmac.new(key, payload, hashlib.sha256).digest()

            with open(self.file_path, "wb") as f:
                f.write(payload)
            with open(self._sig_path, "wb") as f:
                f.write(signature)

    def load(self) -> Any:
        """Load the data from the specified file using pickle, after
        verifying its HMAC-SHA256 integrity signature.

        Returns:
            The data loaded from the file.

        Raises:
            PickleIntegrityError: The pickle file exists but its signing key
                or signature file is missing, or the signature does not
                match the file's contents -- it was not written by this
                handler (or predates this integrity check) and unpickling it
                unconditionally would be unsafe.
        """
        if not os.path.exists(self.file_path):
            return {}

        with store_lock(f"file:{os.path.realpath(self.file_path)}"):
            try:
                with open(self.file_path, "rb") as file:
                    payload = file.read()
            except FileNotFoundError:
                return {}
            if not payload:
                return {}

            try:
                with open(self._key_path, "rb") as f:
                    key = f.read()
                with open(self._sig_path, "rb") as f:
                    expected_signature = f.read()
            except FileNotFoundError as exc:
                raise PickleIntegrityError(
                    f"Refusing to load {self.file_path!r}: no integrity "
                    "signature found alongside it, so it cannot be verified "
                    "as having been written by this handler. Unpickling data "
                    "from an unverified source can execute arbitrary code. "
                    "If you trust this file's origin, delete it (and any "
                    "sibling .key/.sig files) and let it be regenerated; "
                    "otherwise move it aside."
                ) from exc

            actual_signature = hmac.new(key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(actual_signature, expected_signature):
                raise PickleIntegrityError(
                    f"Refusing to load {self.file_path!r}: its integrity "
                    "signature does not match its current contents. It may "
                    "have been modified or replaced since it was last saved "
                    "by this handler."
                )

            try:
                return pickle.loads(payload)  # noqa: S301 -- integrity-verified above
            except EOFError:
                return {}
