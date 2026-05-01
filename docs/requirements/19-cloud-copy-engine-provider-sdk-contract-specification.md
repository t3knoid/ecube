# 19. ECUBE Cloud Copy Engine Provider SDK Contract Specification

| Field | Value |
|---|---|
| Document Title | ECUBE Cloud Copy Engine - Provider SDK Contract Specification |
| Version | 1.0 DRAFT |
| Date | May 2026 |
| Status | Draft for Review |
| Author | Frank Refol |
| Reviewers | TBD |
| Approval | TBD |

**Reference Documents:**

- ECUBE Cloud Copy Engine - Requirements & Specification v1.0
- ECUBE Cloud Copy Engine - RelativityOne API Integration Specification v1.0

## Conformance Language

The key words "SHALL," "SHALL NOT," "SHOULD," "SHOULD NOT," "MUST," "MUST NOT," "MAY," and "OPTIONAL" in this document are to be interpreted as described in RFC 2119.

## 1. Purpose

This document defines the generic provider contract for the ECUBE Cloud Copy Engine (CCE). The CCE is designed with a pluggable provider architecture. The engine itself owns the buffer pool, USB writes, device workers, verification pipeline, retry orchestration, scheduling, and chain-of-custody logging. Cloud source providers are responsible only for the following concerns:

- Authenticating with their cloud platform
- Enumerating files available for export
- Delivering file content as byte streams
- Resolving file metadata (size, hash, names)
- Classifying platform-specific errors into ECUBE's error taxonomy
- Reporting their capabilities so the CCE can adapt behavior

The provider knows nothing about USB devices, buffers, verification, or write transactions. The CCE knows nothing about cloud APIs, authentication protocols, or platform-specific data models. The contract defined here is the seam between them.

This document is handoff-ready: an external developer SHALL be able to implement a complete cloud provider plugin using only this specification and the `ecube_provider_sdk` Python package.

## 2. Architecture Overview

### 2.1 Separation of Concerns

The following table defines the strict boundary between the CCE and any provider implementation. Providers MUST NOT cross into CCE-owned responsibilities, and the CCE SHALL NOT make assumptions about provider-internal behavior.

| CCE Owns (Provider MUST NOT Implement) | Provider Owns (Provider MUST Implement) |
|---|---|
| Buffer pool management (checkout, return, sizing) | Cloud platform authentication and token lifecycle |
| USB device I/O and per-device workers | File enumeration from cloud source (folders, searches, collections, etc.) |
| Transactional write logic (commit/rollback) | Streaming file download (delivering bytes into CCE-provided buffers) |
| Small-file batching and buffer packing | Pre-flight metadata resolution (file size, hash, file name, MIME type) |
| Verification pipeline (calls Shared Verification Service) | Platform-specific error classification into ECUBE's error taxonomy |
| Retry orchestration and circuit breaker logic | Self-describing capability declaration |
| Fairness scheduling across devices | |
| Chain-of-custody logging | |
| Job-level progress aggregation | |
| Cancellation token propagation | |

### 2.2 Plugin Lifecycle

The following sequence describes the complete lifecycle of a provider plugin within a single job execution. The CCE orchestrates all transitions; the provider responds to each call.

1. **Registration.** The provider registers with the CCE via a provider registry, declaring its `provider_id` (for example, `"relativity_one"`, `"azure_blob"`, `"aws_s3"`, `"box"`) and its `CloudProviderCapabilities`.
2. **Initialization.** When a job targets this provider, the CCE calls `initialize()` with the job's provider-specific configuration.
3. **Authentication.** The CCE calls `authenticate()` to establish a session. The provider manages its own token lifecycle internally.
4. **Enumeration.** The CCE calls `enumerate_files()` to obtain the file manifest. The provider returns an async iterator of `CloudFileDescriptor` objects.
5. **Metadata Resolution.** The CCE MAY call `resolve_metadata()` for additional pre-flight checks on specific files.
6. **Download.** For each file, the CCE calls `download_file()`, which returns a `CloudFileStream` - an async byte stream the CCE pipes through its buffer pool.
7. **Error Classification.** On any exception, the CCE calls `classify_error()` to map the exception to ECUBE's retry and escalation taxonomy.
8. **Teardown.** When the job completes, fails, or is cancelled, the CCE calls `shutdown()` for resource cleanup.

## 3. Core Interfaces

This section defines the abstract base classes that constitute the provider contract. All interfaces use Python 3.10+ type annotations and `asyncio` patterns. Providers MUST implement every abstract method. All code targets the `ecube_provider_sdk` package namespace.

### 3.1 ICloudProvider - Main Entry Point

The CCE interacts with the provider exclusively through this interface and its sub-interfaces. One instance is created per job. The provider MUST implement all abstract methods defined below.

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
import asyncio


class ICloudProvider(ABC):
    """
    Main entry point for a cloud provider plugin.

    The CCE interacts with the provider exclusively through this interface and its
    sub-interfaces. One instance is created per job.

    Lifecycle:
        __init__() -> initialize() -> authenticate() -> enumerate_files()
        / download_file() -> shutdown()
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """
        Unique identifier for this provider (for example, 'relativity_one',
        'azure_blob'). MUST be stable across versions. Used in logs and
        configuration keys.
        """

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable provider name for UI and logging."""

    @property
    @abstractmethod
    def capabilities(self) -> "CloudProviderCapabilities":
        """
        Declares what this provider supports. The CCE reads these flags to adapt
        its behavior (for example, skip hash validation if the provider cannot
        supply hashes).
        """

    @abstractmethod
    async def initialize(self, config: "CloudProviderConfig") -> None:
        """
        Initialize the provider with job-specific configuration.

        Called once per job before any other operations. The provider SHOULD
        validate configuration here and raise CloudProviderError with category
        CONFIGURATION if invalid.
        """

    @abstractmethod
    async def authenticate(self) -> "AuthenticationResult":
        """
        Establish an authenticated session with the cloud platform.

        Called after initialize(). The provider manages its own token lifecycle
        internally; the CCE does not manage tokens.
        """

    @abstractmethod
    async def enumerate_files(
        self,
        cancellation_event: asyncio.Event,
    ) -> AsyncIterator["CloudFileDescriptor"]:
        """
        Enumerate all files available for export from the configured source.

        The provider MUST yield files as they are discovered, check
        cancellation_event periodically, and handle pagination internally.
        """

    @abstractmethod
    async def download_file(
        self,
        file_descriptor: "CloudFileDescriptor",
        cancellation_event: asyncio.Event,
    ) -> "CloudFileStream":
        """
        Download a single file and return it as an async byte stream.

        The provider MUST stream file content, not buffer the entire file in
        memory, and MUST support cancellation.
        """

    @abstractmethod
    async def resolve_metadata(
        self,
        file_descriptors: list["CloudFileDescriptor"],
    ) -> list["CloudFileMetadata"]:
        """
        Resolve detailed metadata for a batch of files.

        Called by the CCE for pre-flight validation.
        """

    @abstractmethod
    def classify_error(self, error: Exception) -> "CloudErrorClassification":
        """
        Classify a platform-specific exception into ECUBE's error taxonomy.

        This method MUST NOT raise exceptions. If classification itself fails,
        return CloudErrorClassification with category UNKNOWN.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Clean up provider resources.

        Called when the job completes, fails, or is cancelled. This method MUST
        NOT raise exceptions.
        """
```

### 3.2 CloudFileStream - Stream Wrapper

The `CloudFileStream` is the byte-level transport interface between the provider and the CCE. The provider controls how bytes are fetched (HTTP streaming, SDK calls, and so on); the CCE controls how much it reads and when.

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class CloudFileStream(ABC):
    """
    Async byte stream returned by ICloudProvider.download_file().

    The CCE reads from this stream to fill its buffer pool. The provider controls
    how bytes are fetched, but the CCE controls how much it reads and when.
    """

    @property
    @abstractmethod
    def content_length(self) -> Optional[int]:
        """Total size in bytes if known, None otherwise."""

    @property
    @abstractmethod
    def file_descriptor(self) -> "CloudFileDescriptor":
        """The file descriptor this stream is delivering."""

    @abstractmethod
    async def read(self, size: int = -1) -> bytes:
        """Read up to `size` bytes from the stream."""

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[bytes]:
        """Async iterate over the stream in chunks."""

    @abstractmethod
    async def __anext__(self) -> bytes:
        """Return the next chunk of bytes and raise StopAsyncIteration at EOF."""

    @abstractmethod
    async def close(self) -> None:
        """Release underlying resources. MUST be idempotent."""

    async def __aenter__(self) -> "CloudFileStream":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
```

## 4. Data Models

All data models are defined as Python dataclasses with full type annotations. Frozen dataclasses are used where immutability is required.

### 4.1 CloudFileDescriptor

The universal currency exchanged between the provider and the CCE. The provider creates these during enumeration; the CCE uses them to drive downloads, writes, and chain-of-custody logging. Immutable (`frozen=True`) - once created during enumeration, descriptors SHALL NOT change.

```python
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum
import datetime


class FileType(Enum):
    """Type of file being downloaded."""

    NATIVE = "native"
    IMAGE = "image"
    PDF = "pdf"
    TEXT = "text"
    METADATA = "metadata"
    OTHER = "other"


@dataclass(frozen=True)
class CloudFileDescriptor:
    """Describes a single downloadable file from the cloud source."""

    source_id: str
    source_name: str
    target_relative_path: str
    file_type: FileType
    expected_size_bytes: Optional[int] = None
    expected_hash: Optional[str] = None
    mime_type: Optional[str] = None
    group_id: Optional[str] = None
    sequence_in_group: int = 0
    provider_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime.datetime] = None
    modified_at: Optional[datetime.datetime] = None
```

### 4.2 CloudFileMetadata

Enriched metadata returned by `resolve_metadata()`. Extends the file descriptor with detailed, verified metadata for pre-flight validation. The CCE compares these values against actual download results.

```python
@dataclass
class CloudFileMetadata:
    """Enriched metadata returned by resolve_metadata()."""

    file_descriptor: CloudFileDescriptor
    verified_size_bytes: Optional[int] = None
    verified_hash: Optional[str] = None
    is_available: bool = True
    unavailability_reason: Optional[str] = None
    additional_hashes: Dict[str, str] = field(default_factory=dict)
```

### 4.3 CloudProviderCapabilities

Self-describing capability flags that tell the CCE what the provider supports. The CCE reads these to adapt its behavior. Providers MUST set these accurately - declaring a capability not supported will cause runtime failures; omitting a supported capability will cause the CCE to skip optimizations.

```python
@dataclass(frozen=True)
class CloudProviderCapabilities:
    supports_hash: bool = False
    hash_algorithms: tuple[str, ...] = ()
    supports_file_size: bool = True
    supports_streaming: bool = True
    supports_resumable_download: bool = False
    supports_concurrent_downloads: bool = True
    max_concurrent_downloads: Optional[int] = None
    supports_server_side_enumeration: bool = True
    supports_groups: bool = False
    supports_metadata_export: bool = False
    rate_limited: bool = False
    provider_version: str = "1.0.0"
    sdk_contract_version: str = "1.0.0"
```

### 4.4 CloudProviderConfig

Configuration passed to the provider during initialization. Contains both ECUBE-standard fields and a provider-specific settings dictionary. The provider reads its settings from `provider_settings` using its own configuration schema.

```python
@dataclass
class CloudProviderConfig:
    job_id: str
    provider_id: str
    provider_settings: Dict[str, Any] = field(default_factory=dict)
    credential_settings: Dict[str, Any] = field(default_factory=dict)
    max_concurrent_downloads: int = 8
    bandwidth_limit_bytes_per_sec: int = 0
    download_timeout_seconds: int = 300
```

Representative `provider_settings` examples:

```python
{
    "instance_url": "https://myinstance.relativity.one",
    "workspace_id": 1018234,
    "source_type": "saved_search",
    "source_artifact_id": 1039567,
    "export_file_types": ["native", "image"],
    "view_id": 1003684,
}
```

```python
{
    "account_name": "myaccount",
    "container_name": "exports",
    "prefix": "case-2024-001/",
}
```

```python
{
    "bucket": "legal-exports",
    "prefix": "matter-42/",
    "region": "us-east-1",
}
```

### 4.5 AuthenticationResult

```python
@dataclass
class AuthenticationResult:
    """Result of a provider authentication attempt."""

    success: bool
    session_id: Optional[str] = None
    expires_at: Optional[datetime.datetime] = None
    identity: Optional[str] = None
    error_message: Optional[str] = None
```

### 4.6 CloudErrorClassification

ECUBE's error taxonomy is defined by the `ErrorCategory` enumeration. Providers map their platform-specific errors into these categories. The CCE uses the category to determine retry behavior.

```python
class ErrorCategory(Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    AUTHENTICATION = "authentication"
    CONFIGURATION = "configuration"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


@dataclass
class CloudErrorClassification:
    category: ErrorCategory
    retry_after_seconds: Optional[float] = None
    is_retryable: bool = True
    original_error_code: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
```

### 4.7 CloudProviderError

Base exception for all provider errors. Providers SHOULD raise this (or subclasses) for all anticipated errors. If a provider raises a non-`CloudProviderError` exception, the CCE will call `classify_error()` to categorize it, but structured errors are preferred.

```python
class CloudProviderError(Exception):
    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        original_error: Optional[Exception] = None,
        error_code: Optional[str] = None,
        retry_after_seconds: Optional[float] = None,
    ):
        super().__init__(message)
        self.category = category
        self.original_error = original_error
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds
```

## 5. Provider Registration & Discovery

### 5.1 Provider Registry

Providers register themselves with the CCE's provider registry. Registration MAY be performed via a class decorator or a programmatic call. The registry uses the `provider_id` as the lookup key.

**Decorator registration (preferred):**

```python
from ecube_provider_sdk import provider_registry


@provider_registry.register
class MyCloudProvider(ICloudProvider):
    @property
    def provider_id(self) -> str:
        return "my_cloud"
```

**Programmatic registration:**

```python
from ecube_provider_sdk import provider_registry

provider_registry.register_provider("my_cloud", MyCloudProvider)
```

### 5.2 Provider Factory

The CCE uses a factory to instantiate providers internally. Providers do not interact with this class directly but MUST support multiple concurrent instances (one per job).

```python
class ProviderFactory:
    """Creates provider instances for jobs. The CCE uses this internally."""

    def create(self, provider_id: str) -> ICloudProvider:
        """Instantiate a provider by its registered ID."""
```

### 5.3 Package Structure

Provider plugins SHALL be structured as installable Python packages. The following layout is the recommended convention:

```text
ecube_provider_my_cloud/
|-- __init__.py
|-- provider.py
|-- downloader.py
|-- enumerator.py
|-- auth.py
|-- error_mapping.py
|-- config_schema.py
|-- requirements.txt
`-- tests/
    |-- test_provider.py
    |-- test_downloader.py
    |-- test_enumerator.py
    `-- conftest.py
```

Package naming convention: all provider packages MUST be named `ecube_provider_{provider_id}` where `{provider_id}` matches the value returned by `ICloudProvider.provider_id`. The `__init__.py` file MUST call `provider_registry.register` at import time so the CCE discovers the provider upon package installation.

## 6. Behavioral Contracts

This section specifies the detailed behavioral rules that all providers MUST follow. Violation of any MUST-level rule constitutes a contract breach and may cause undefined CCE behavior.

### 6.1 Streaming Contract

6.1.1 The `download_file()` method MUST return a `CloudFileStream` that delivers bytes incrementally. The provider MUST NOT buffer the entire file in memory.

6.1.2 Chunk sizes SHOULD be between 64 KB and 1 MB. The CCE handles buffer management; the provider yields chunks only.

6.1.3 The stream MUST be usable as an async context manager (`async with`). The CCE SHALL always call `close()`, even on error.

6.1.4 If a download is cancelled (`cancellation_event` is set), the stream SHOULD stop yielding data promptly (within 1 second) and allow `close()` to complete without blocking.

### 6.2 Enumeration Contract

6.2.1 `enumerate_files()` MUST return an `AsyncIterator` that yields `CloudFileDescriptor` objects one at a time. Providers MUST NOT collect all files into a list before yielding.

6.2.2 The iterator MUST handle pagination internally. The CCE sees a single flat stream regardless of the underlying API's pagination model.

6.2.3 Descriptors MUST have unique `source_id` values within a single enumeration. Duplicate `source_id` values constitute a contract violation.

6.2.4 If `group_id` is used, all files in a group MUST be yielded contiguously, not interleaved with other groups.

6.2.5 The `target_relative_path` MUST use forward slashes only, MUST NOT start with a slash, and MUST NOT contain `..` segments.

### 6.3 Error Contract

6.3.1 Providers SHOULD raise `CloudProviderError` for all anticipated errors with the appropriate `ErrorCategory`.

6.3.2 `classify_error()` MUST handle all possible exceptions the provider might raise, including unexpected ones. It MUST NOT itself raise any exception.

6.3.3 For rate-limited platforms, the provider SHOULD extract the server's retry-after directive and include it in `CloudErrorClassification.retry_after_seconds`.

6.3.4 Authentication errors (HTTP 401 equivalents) MUST be classified as `AUTHENTICATION`, not `TRANSIENT`. Misclassification will prevent the CCE from invoking the re-authentication flow.

### 6.4 Thread Safety Contract

6.4.1 Provider instances are used by a single job, but the CCE MAY call `download_file()` concurrently from multiple tasks up to `max_concurrent_downloads`.

6.4.2 Providers MUST be safe for concurrent `download_file()` calls. Shared state, such as HTTP session pools or token caches, MUST be protected with appropriate synchronization primitives.

6.4.3 `enumerate_files()` is called from a single task.

6.4.4 `classify_error()` MUST be safe for concurrent calls from multiple tasks.

6.4.5 Providers MUST NOT use global mutable state. All state MUST be instance-level.

### 6.5 Resource Management Contract

6.5.1 Providers MUST release all resources (HTTP connections, open files, SDK clients) in `shutdown()`.

6.5.2 `shutdown()` MUST be idempotent and safe to call multiple times without side effects.

6.5.3 `shutdown()` MUST complete within 10 seconds. The CCE MAY forcibly terminate the provider after this timeout.

6.5.4 Providers MUST NOT hold references to CCE-internal objects (buffers, workers, device handles, and so on).

## 7. How The CCE Uses The Provider

This section walks through the CCE's internal usage of the provider interface. The pseudo-code below is provided to help implementors understand the call patterns and timing. Providers do NOT implement any of this code; it is shown for context only.

### 7.1 Job Execution Flow

The following pseudo-code illustrates how the CCE orchestrates the full lifecycle of a job, calling provider methods at each phase:

```python
# Simplified CCE job execution (pseudo-code).
# Shows how the CCE calls provider methods - providers do NOT implement this.

async def execute_job(job: Job, provider: ICloudProvider) -> JobResult:
    cancel_event = asyncio.Event()

    config = CloudProviderConfig(
        job_id=job.id,
        provider_id=job.provider_id,
        provider_settings=job.provider_settings,
        credential_settings=vault.get_credentials(job.credential_ref),
    )
    await provider.initialize(config)
    auth_result = await provider.authenticate()

    file_queue: asyncio.Queue[CloudFileDescriptor] = asyncio.Queue()
    async for descriptor in provider.enumerate_files(cancel_event):
        file_queue.put_nowait(descriptor)

    if provider.capabilities.supports_hash or provider.capabilities.supports_file_size:
        all_files = list(file_queue._queue)
        metadata = await provider.resolve_metadata(all_files)
        validate_metadata(metadata)

    async def process_file(descriptor: CloudFileDescriptor, device_worker):
        stream = await provider.download_file(descriptor, cancel_event)
        async with stream:
            buffer = buffer_pool.checkout()
            try:
                async for chunk in stream:
                    buffer.write(chunk)
                    if buffer.is_full:
                        await device_worker.write_transactional(buffer)
                        buffer_pool.return_buffer(buffer)
                        buffer = buffer_pool.checkout()

                if buffer.position > 0:
                    await device_worker.write_transactional(buffer)
            finally:
                buffer_pool.return_buffer(buffer)

        verify_result = await verification_service.verify(
            device_path=device_worker.get_file_path(descriptor),
            expected_hash=descriptor.expected_hash,
        )

        await logging_service.log_chain_of_custody(
            job_id=job.id,
            source_id=descriptor.source_id,
            provider_metadata=descriptor.provider_metadata,
            verify_result=verify_result,
        )

    workers = [process_file(desc, device) for desc, device in assignments]
    results = await asyncio.gather(*workers, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            classification = provider.classify_error(result)
            handle_error(classification)

    await provider.shutdown()
    return aggregate_results(results)
```

### 7.2 Error Handling Flow

The following pseudo-code shows how the CCE handles errors using the provider's `classify_error()` method. Note the distinct handling per `ErrorCategory`:

```python
async def download_with_retry(
    provider: ICloudProvider,
    descriptor: CloudFileDescriptor,
    cancel_event: asyncio.Event,
    max_retries: int = 3,
) -> CloudFileStream:
    retries = 0
    while True:
        try:
            return await provider.download_file(descriptor, cancel_event)
        except Exception as error:
            classification = provider.classify_error(error)
            if classification.category == ErrorCategory.RATE_LIMITED:
                await asyncio.sleep(classification.retry_after_seconds or 5.0)
                continue
            if classification.category == ErrorCategory.AUTHENTICATION:
                await provider.authenticate()
                retries += 1
            elif classification.category == ErrorCategory.PERMANENT:
                raise
            elif classification.category == ErrorCategory.CONFIGURATION:
                raise
            elif classification.is_retryable and retries < max_retries:
                backoff = min(
                    BASE_BACKOFF * (2 ** retries) + random.uniform(0, 1),
                    MAX_BACKOFF,
                )
                await asyncio.sleep(backoff)
                retries += 1
            else:
                raise
```

## 8. Reference Implementation: Minimal File System Provider

The following is a complete, working reference implementation that reads files from a local directory. It demonstrates the contract without any cloud SDK complexity and is suitable for testing and as a starting point for new provider implementations.

### 8.1 LocalFileStream

```python
"""Minimal reference provider: reads files from a local directory."""

import aiofiles
from pathlib import Path
from typing import AsyncIterator, Optional


class LocalFileStream(CloudFileStream):
    """Streams a local file asynchronously."""

    def __init__(self, path: Path, descriptor: CloudFileDescriptor):
        self._path = path
        self._descriptor = descriptor
        self._file = None
        self._size = path.stat().st_size

    @property
    def content_length(self) -> Optional[int]:
        return self._size

    @property
    def file_descriptor(self) -> CloudFileDescriptor:
        return self._descriptor

    async def read(self, size: int = -1) -> bytes:
        if self._file is None:
            self._file = await aiofiles.open(self._path, "rb")
        if size == -1:
            return await self._file.read()
        return await self._file.read(size)

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self) -> bytes:
        chunk = await self.read(256 * 1024)
        if not chunk:
            raise StopAsyncIteration
        return chunk

    async def close(self) -> None:
        if self._file is not None:
            await self._file.close()
            self._file = None
```

### 8.2 LocalDirectoryProvider

```python
import asyncio
import hashlib
import os
from pathlib import Path
from typing import AsyncIterator, Optional


class LocalDirectoryProvider(ICloudProvider):
    """Reference implementation for a local directory source."""

    def __init__(self):
        self._root: Optional[Path] = None

    @property
    def provider_id(self) -> str:
        return "local_directory"

    @property
    def display_name(self) -> str:
        return "Local Directory (Reference)"

    @property
    def capabilities(self) -> CloudProviderCapabilities:
        return CloudProviderCapabilities(
            supports_hash=True,
            hash_algorithms=("sha256",),
            supports_file_size=True,
            supports_streaming=True,
            supports_resumable_download=False,
            supports_concurrent_downloads=True,
            max_concurrent_downloads=16,
            supports_groups=False,
            supports_metadata_export=False,
            rate_limited=False,
        )

    async def initialize(self, config: CloudProviderConfig) -> None:
        root = config.provider_settings.get("root_directory")
        if not root:
            raise CloudProviderError(
                "root_directory is required",
                category=ErrorCategory.CONFIGURATION,
            )
        self._root = Path(root)
        if not self._root.is_dir():
            raise CloudProviderError(
                f"Directory not found: {self._root}",
                category=ErrorCategory.CONFIGURATION,
            )

    async def authenticate(self) -> AuthenticationResult:
        return AuthenticationResult(success=True, identity="local")

    async def enumerate_files(
        self,
        cancellation_event: asyncio.Event,
    ) -> AsyncIterator[CloudFileDescriptor]:
        for root, dirs, files in os.walk(self._root):
            for name in sorted(files):
                if cancellation_event.is_set():
                    return
                full_path = Path(root) / name
                rel_path = full_path.relative_to(self._root)
                sha = hashlib.sha256()
                with open(full_path, "rb") as handle:
                    for block in iter(lambda: handle.read(65536), b""):
                        sha.update(block)
                yield CloudFileDescriptor(
                    source_id=str(rel_path),
                    source_name=name,
                    target_relative_path=str(rel_path).replace("\\", "/"),
                    file_type=FileType.NATIVE,
                    expected_size_bytes=full_path.stat().st_size,
                    expected_hash=f"sha256:{sha.hexdigest()}",
                    mime_type=None,
                )

    async def download_file(
        self,
        file_descriptor: CloudFileDescriptor,
        cancellation_event: asyncio.Event,
    ) -> CloudFileStream:
        path = self._root / file_descriptor.source_id
        if not path.exists():
            raise CloudProviderError(
                f"File not found: {path}",
                category=ErrorCategory.PERMANENT,
                error_code="FILE_NOT_FOUND",
            )
        return LocalFileStream(path, file_descriptor)

    async def resolve_metadata(
        self,
        file_descriptors: list[CloudFileDescriptor],
    ) -> list[CloudFileMetadata]:
        results = []
        for descriptor in file_descriptors:
            path = self._root / descriptor.source_id
            results.append(
                CloudFileMetadata(
                    file_descriptor=descriptor,
                    verified_size_bytes=path.stat().st_size if path.exists() else None,
                    verified_hash=descriptor.expected_hash,
                    is_available=path.exists(),
                    unavailability_reason=None if path.exists() else "File not found",
                )
            )
        return results

    def classify_error(self, error: Exception) -> CloudErrorClassification:
        if isinstance(error, CloudProviderError):
            return CloudErrorClassification(
                category=error.category,
                is_retryable=(error.category == ErrorCategory.TRANSIENT),
                original_error_code=error.error_code,
                message=str(error),
            )
        if isinstance(error, FileNotFoundError):
            return CloudErrorClassification(
                category=ErrorCategory.PERMANENT,
                is_retryable=False,
                original_error_code="FILE_NOT_FOUND",
                message=str(error),
            )
        if isinstance(error, PermissionError):
            return CloudErrorClassification(
                category=ErrorCategory.PERMANENT,
                is_retryable=False,
                original_error_code="PERMISSION_DENIED",
                message=str(error),
            )
        return CloudErrorClassification(
            category=ErrorCategory.UNKNOWN,
            message=str(error),
        )

    async def shutdown(self) -> None:
        self._root = None
```

## 9. Provider Developer Checklist

The following checklist summarizes every task a provider developer MUST complete before submitting a provider for integration testing.

| # | Task | Contract Reference |
|---|---|---|
| 1 | Implement `ICloudProvider` with all 8 required methods | Section 3.1 |
| 2 | Implement `CloudFileStream` for streaming downloads | Section 3.2 |
| 3 | Define `CloudProviderCapabilities` accurately | Section 4.3 |
| 4 | Document `provider_settings` schema with examples | Section 4.4 |
| 5 | Map all platform errors to `ErrorCategory` | Section 4.6 |
| 6 | Handle rate limiting internally and surface via `classify_error()` | Section 6.3 |
| 7 | Ensure thread safety for concurrent `download_file()` calls | Section 6.4 |
| 8 | Ensure `enumerate_files()` yields contiguous groups | Section 6.2 |
| 9 | Ensure `shutdown()` completes within 10 seconds | Section 6.5 |
| 10 | Write unit tests using `ecube_provider_sdk.testing` mocks | Section 10 |
| 11 | Register provider via `@provider_registry.register` | Section 5.1 |
| 12 | Package as installable Python package with correct naming | Section 5.3 |

## 10. Testing Support

The `ecube_provider_sdk.testing` module provides test utilities that simulate the CCE's call patterns against a provider. Providers SHOULD use these utilities to validate contract compliance before integration testing.

### 10.1 MockCCEHarness

The `MockCCEHarness` simulates the CCE's complete lifecycle call pattern against a provider instance. It exercises initialization, authentication, enumeration, download, and shutdown in the same order and with the same concurrency patterns as the production CCE.

```python
from ecube_provider_sdk.testing import MockCCEHarness


async def test_my_provider():
    provider = MyCloudProvider()
    harness = MockCCEHarness(provider)
    config = CloudProviderConfig(
        job_id="test-001",
        provider_id="my_cloud",
        provider_settings={"...": "..."},
        credential_settings={"...": "..."},
    )

    result = await harness.run_full_lifecycle(config)
    assert result.authentication_success
    assert result.files_enumerated > 0
    assert result.files_downloaded == result.files_enumerated
    assert result.errors == []
```

### 10.2 Contract Compliance Tests

The SDK includes a pre-built test suite that validates contract compliance. Provider developers extend the base class and supply a provider instance and configuration:

```python
from ecube_provider_sdk.testing import ContractComplianceTests


class TestMyProviderCompliance(ContractComplianceTests):
    """Runs the standard compliance test suite against your provider."""

    def create_provider(self) -> ICloudProvider:
        return MyCloudProvider()

    def create_config(self) -> CloudProviderConfig:
        return CloudProviderConfig(
            job_id="compliance-test",
            provider_id="my_cloud",
            provider_settings={"root_directory": "/tmp/test-data"},
            credential_settings={},
        )
```

The compliance suite validates the following behaviors:

- `enumerate_files()` yields valid `CloudFileDescriptor` objects with unique `source_id` values
- `download_file()` returns a valid `CloudFileStream` that yields bytes
- Streams support the async context manager protocol (`async with`)
- `classify_error()` handles standard Python exceptions without raising
- `shutdown()` completes within the 10-second timeout
- Concurrent `download_file()` calls do not interfere with each other
- Cancellation is respected within 2 seconds
- Capability flags are consistent, for example `hash_algorithms` is non-empty if `supports_hash` is `True`

## 11. Capability-Driven CCE Adaptation

The CCE reads `CloudProviderCapabilities` at job startup and adapts its behavior accordingly. The following table defines the exact behavioral differences for each capability flag:

| Capability Flag | CCE Behavior When True | CCE Behavior When False |
|---|---|---|
| `supports_hash` | Pre-flight hash validation enabled; post-write verification compares against provider hash. | Hash validation skipped during pre-flight; post-write verification uses size-only check or re-download comparison. |
| `supports_file_size` | Progress bars show percentage; buffer pre-allocation optimized based on known sizes. | Progress shows bytes transferred only; buffers filled dynamically. |
| `supports_resumable_download` | On interrupted download, CCE resumes from last byte offset. | On interrupted download, CCE restarts from byte 0. |
| `supports_concurrent_downloads` | CCE opens multiple download streams up to `min(provider.max, cce.max)`. | CCE serializes all downloads through a single stream. |
| `supports_groups` | CCE wraps a file group into a document-level transaction; all-or-nothing commit per group. | Each file is its own independent transaction. |
| `supports_metadata_export` | CCE requests a companion metadata or load file from the provider and writes it to USB. | No companion metadata file generated from provider. |
| `rate_limited` | CCE honors `retry_after_seconds` from `classify_error()`; rate-limited retries do not count against retry limits. | CCE uses standard exponential backoff on all transient errors. |

Accuracy requirement: providers MUST set capability flags accurately. Declaring `supports_hash=True` when the platform does not provide hashes will cause pre-flight validation failures. Declaring `supports_concurrent_downloads=False` when concurrency is supported will unnecessarily serialize downloads and degrade performance.

## 12. Versioning & Compatibility

The SDK contract follows semantic versioning (SemVer). The version is tracked in `CloudProviderCapabilities.sdk_contract_version` and checked by the CCE at runtime.

| Version Change | Example | Impact on Providers |
|---|---|---|
| Major version bump | 1.x -> 2.x | Breaking changes to interface signatures. Providers MUST update their implementation to match the new contract. The CCE SHALL reject providers targeting an incompatible major version. |
| Minor version bump | 1.0 -> 1.1 | New optional methods or capability flags added. Existing providers continue to work without modification. New methods have default implementations in the ABC. |
| Patch version bump | 1.0.0 -> 1.0.1 | Bug fixes in SDK utilities only. No contract changes. Providers are unaffected. |

**Compatibility rules:**

- The CCE checks `capabilities.sdk_contract_version` at runtime and SHALL reject providers targeting an incompatible major version.
- Providers SHOULD pin to a specific minor version and run the compliance test suite against it.
- When the CCE is upgraded to a new minor version, existing providers SHALL continue to function without recompilation or code changes.
- Deprecation notices for methods or flags SHALL appear in a minor release, and the deprecated feature SHALL remain functional for at least one additional minor release before removal in a major release.

## 13. Glossary

| Term | Definition |
|---|---|
| **Provider** | A plugin module that implements `ICloudProvider` to connect the CCE to a specific cloud platform, for example RelativityOne, Azure Blob Storage, AWS S3, or Box. |
| **Provider Registry** | The CCE-internal registry that maps `provider_id` strings to provider classes. Populated at application startup via the `@provider_registry.register` decorator or programmatic registration. |
| **CloudFileDescriptor** | An immutable data object describing a single downloadable file from the cloud source. Created during enumeration and used throughout the download, write, and verification pipeline. |
| **CloudFileStream** | An abstract async byte stream that wraps a file download. The provider delivers bytes through this interface; the CCE consumes them into its buffer pool. |
| **Capability Flags** | Boolean and scalar values in `CloudProviderCapabilities` that describe what a provider supports. The CCE reads these flags to adapt its runtime behavior. |
| **Error Taxonomy** | The classification system defined by `ErrorCategory` that maps platform-specific errors into CCE-understood categories: `TRANSIENT`, `PERMANENT`, `AUTHENTICATION`, `CONFIGURATION`, `RATE_LIMITED`, and `UNKNOWN`. |
| **Group ID** | An optional identifier on `CloudFileDescriptor` that groups related files into a logical unit, such as a document with native, image, and text renditions. The CCE uses group IDs for document-level transactional writes. |
| **Chain-of-Custody** | The CCE's tamper-evident logging system that records every file's journey from cloud source to USB device, including source identifiers, provider metadata, hash values, verification results, and timestamps. |
| **Contract Compliance** | The state of a provider implementation meeting all MUST-level requirements in this specification. Verified via the `ContractComplianceTests` suite provided in `ecube_provider_sdk.testing`. |
| **MockCCEHarness** | A test utility class provided by `ecube_provider_sdk.testing` that simulates the CCE's lifecycle call pattern against a provider without requiring the full CCE runtime. |

**ECUBE Cloud Copy Engine - Provider SDK Contract Specification**

Version 1.0 DRAFT | May 2026 | Status: Draft for Review

(c) Frank Refol. All rights reserved. This document is confidential and intended solely for the use of authorized provider developers.