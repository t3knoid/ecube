# 21. ECUBE Cloud Copy Engine RelativityOne Provider Implementation Guide

| Field | Value |
|---|---|
| Document Title | Implementing a RelativityOne Export Plugin for the ECUBE Cloud Copy Engine |
| Version | 1.0 DRAFT |
| Date | May 2026 |
| Status | Draft for Review |
| Author | Frank Refol |
| Reviewers | TBD |
| Approval | TBD |

### Reference Documents

- ECUBE Cloud Copy Engine - Requirements & Specification v1.0
- ECUBE Cloud Copy Engine - RelativityOne API Integration Specification v1.0
- ECUBE Cloud Copy Engine - Provider SDK Contract Specification v1.0

## Table of Contents

1. Introduction
2. Constants and Configuration
3. Authentication - auth.py
4. Rate Limiter - rate_limiter.py
5. File Enumeration - enumerator.py
6. File Downloading - downloader.py
7. Error Classification - error_mapping.py
8. Metadata Resolution - metadata.py
9. The Main Provider - provider.py
10. Provider Registration - __init__.py
11. Testing Strategy
12. Deployment and Configuration
13. Operational Runbook
14. Appendix: RelativityOne Object Manager Query Reference

## 1. Introduction

### 1.1 Purpose

This document is the implementation guide for the RelativityOne cloud provider plugin (`ecube_provider_relativity`). It implements the ECUBE Cloud Copy Engine Provider SDK contract, enabling ECUBE to export documents from RelativityOne workspaces directly to USB storage devices.

This is the engineer-facing implementation guide for building the provider. The artifact presents complete code listings, concrete API patterns, and design rationale rather than placeholder stubs.

Prerequisites for the reader:

- Familiarity with RelativityOne REST APIs and the Kepler framework
- Understanding of the ECUBE Provider SDK contract
- Python 3.10+ and asyncio proficiency

### 1.2 Design Strategy Recap

The integration follows a dual-strategy architecture.

- Primary download path: Document File Manager API. Files are streamed through HTTP response bodies directly into ECUBE's buffer pool and then to USB without local disk staging.
- Manifest and enumeration: Object Manager API. Document metadata is queried through `/objects/query` to build the file manifest.
- Authentication: OAuth2 Client Credentials via `/Relativity/Identity/connect/token` with proactive token refresh.
- Rate limiting: dynamic throttling based on `RateLimit-Limit`, `RateLimit-Remaining`, and `RateLimit-Reset` headers, coordinated through a shared `KeplerRateLimitGuard`.

### 1.3 Package Structure

The package layout in the artifact is:

```text
ecube_provider_relativity/
├── __init__.py
├── provider.py
├── auth.py
├── enumerator.py
├── downloader.py
├── metadata.py
├── error_mapping.py
├── rate_limiter.py
├── models.py
├── constants.py
├── config_schema.py
├── load_file_writer.py
├── requirements.txt
└── tests/
    ├── conftest.py
    ├── test_provider.py
    ├── test_auth.py
    ├── test_enumerator.py
    ├── test_downloader.py
    ├── test_error_mapping.py
    ├── test_rate_limiter.py
    └── fixtures/
```

The artifact notes that `load_file_writer.py` is referenced for Concordance DAT and Opticon output but is not fully implemented inside the guide.

## 2. Constants and Configuration

### 2.1 constants.py

This module centralizes RelativityOne API endpoint patterns, well-known artifact type and field IDs, and default runtime values. Paths use `{placeholder}` substitution and are formatted at runtime.

Representative definitions from the artifact:

```python
"""RelativityOne API endpoint patterns and default configuration values."""

OBJECT_MANAGER_QUERY = (
    "/Relativity.REST/api/relativity-object-manager/v1"
    "/workspaces/{workspace_id}/objects/query"
)
DOCUMENT_FILE_INFO = (
    "/Relativity.REST/api/relativity-object-model/v1"
    "/workspaces/{workspace_id}/documents/{document_id}/files"
)
NATIVE_FILE_DOWNLOAD = (
    "/Relativity.REST/api/relativity-object-model/v1"
    "/workspaces/{workspace_id}/documents/{document_id}/native-file"
)
FILE_DOWNLOAD_BY_GUID = (
    "/Relativity.REST/api/relativity-object-model/v1"
    "/workspaces/{workspace_id}/files/{file_guid}"
)
EXPORT_SERVICE_JOBS = "/export/v1/workspaces/{workspace_id}/jobs"
EXPORT_SERVICE_JOB = "/export/v1/workspaces/{workspace_id}/jobs/{job_id}"
OAUTH2_TOKEN = "/Relativity/Identity/connect/token"

DOCUMENT_ARTIFACT_TYPE_ID = 10
FOLDER_ARTIFACT_TYPE_ID = 9

CONTROL_NUMBER_FIELD_ID = 1003667
FILE_SIZE_FIELD_ID = 1003668
FILE_NAME_FIELD_ID = 1003669
ARTIFACT_ID_FIELD_ID = 1003670

DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_CONCURRENT_API = 4
DEFAULT_TOKEN_REFRESH_PERCENT = 80
DEFAULT_DOWNLOAD_TIMEOUT = 300
DEFAULT_RATE_LIMIT_BACKOFF_MULTIPLIER = 1.5
DEFAULT_CHUNK_SIZE = 262144

CSRF_HEADER = "X-CSRF-Header"
CSRF_HEADER_VALUE = "-"
KEPLER_REFERRER_HEADER = "X-Kepler-Referrer"
```

Important artifact note: the `X-CSRF-Header` header with the literal value `"-"` is mandatory for RelativityOne REST calls. Omitting it results in a `403 Forbidden` response.

### 2.2 config_schema.py

The guide defines a provider-specific configuration schema that validates `provider_settings` from `CloudProviderConfig` during provider initialization. The artifact uses a plain dataclass rather than Pydantic to keep the dependency footprint minimal.

Core configuration types:

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExportSourceType(Enum):
    FOLDER = "folder"
    SAVED_SEARCH = "saved_search"
    PRODUCTION = "production"


class ExportFileType(Enum):
    NATIVE = "native"
    IMAGE = "image"
    PDF = "pdf"
    FULL_TEXT = "full_text"


@dataclass
class RelativityOneConfig:
    instance_url: str
    workspace_id: int
    source_type: ExportSourceType
    source_artifact_id: int
    view_id: int
    export_file_types: list[ExportFileType] = field(default_factory=lambda: [ExportFileType.NATIVE])
    include_subfolders: bool = True
    hash_field_artifact_id: Optional[int] = None
    control_number_field_id: int = 1003667
    additional_field_ids: list[int] = field(default_factory=list)
    page_size: int = 1000
    max_concurrent_api_requests: int = 4
    token_refresh_threshold_percent: int = 80
    download_timeout_seconds: int = 300
    download_chunk_size: int = 262144
    rate_limit_backoff_multiplier: float = 1.5
    app_guid: str = ""
    native_subdirectory_prefix: str = "NATIVES"
    image_subdirectory_prefix: str = "IMAGES"
    pdf_subdirectory_prefix: str = "PDFS"
    text_subdirectory_prefix: str = "TEXT"
    volume_prefix: str = "VOL"
    volume_max_size_gb: float = 4.0
    generate_load_file: bool = True
```

The `from_provider_settings()` parser validates required fields, parses enum values, normalizes optional fields, and raises a `CloudProviderError(CONFIGURATION)` with accumulated validation messages if parsing fails.

## 3. Authentication - auth.py

### 3.1 RelativityOneAuthManager

The authentication manager handles OAuth2 Client Credentials flow, proactive token refresh, thread-safe token access through `asyncio.Lock`, and a single retry on `401` responses before escalating to an authentication failure.

Representative structure:

```python
@dataclass
class TokenState:
    access_token: str
    token_type: str
    expires_at: float
    scope: str = ""


class RelativityOneAuthManager:
    def __init__(self, config: RelativityOneConfig):
        self._config = config
        self._token_state: Optional[TokenState] = None
        self._lock = asyncio.Lock()
        self._client_id: str = ""
        self._client_secret: str = ""
        self._session: Optional[aiohttp.ClientSession] = None
        self._refresh_threshold = config.token_refresh_threshold_percent / 100.0
        self._token_url = f"{config.instance_url}{OAUTH2_TOKEN}"
```

Behavioral requirements described in the artifact:

- Acquire tokens with `grant_type=client_credentials`.
- Never persist tokens to disk.
- Never log access tokens or client secrets.
- Refresh tokens when the remaining lifetime falls into the final configured percentage of the TTL.
- On `401`, attempt exactly one refresh and retry path before surfacing an authentication error.

Design decision from the artifact: proactive refresh prevents a race where a download starts with a valid token but the token expires before the response completes.

## 4. Rate Limiter - rate_limiter.py

### 4.1 KeplerRateLimitGuard

The guide uses a shared rate-limit guard across concurrent workers to enforce RelativityOne's dynamic throttling model. It tracks rate-limit headers, pauses before budget exhaustion, and blocks new requests when a `429` is returned.

Representative interface:

```python
class KeplerRateLimitGuard:
    def __init__(self, backoff_multiplier: float = 1.5):
        self._backoff_multiplier = backoff_multiplier
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._blocked_until: float = 0.0
        self._lock = asyncio.Lock()
        self._rate_limit: Optional[int] = None
        self._rate_remaining: Optional[int] = None
        self._rate_reset: Optional[float] = None

    def set_concurrency(self, max_concurrent: int) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def acquire(self) -> None:
        ...

    def release(self) -> None:
        ...

    async def record_response_headers(self, headers: dict) -> None:
        ...

    async def record_rate_limited(self, retry_after_seconds: float) -> None:
        ...
```

Key guard behavior:

- Coordinate all workers against the same request budget.
- Sleep until reset when the budget is nearly exhausted.
- Multiply server-provided retry delays by a configurable backoff multiplier.
- Separate request-initiation throttling from actual byte streaming.

## 5. File Enumeration - enumerator.py

### 5.1 RelativityOneFileEnumerator

The enumerator is the most complex provider component. It pages through documents with the Object Manager API, queries the Document File Manager for each document's associated files, and yields `CloudFileDescriptor` objects grouped by document.

Representative structure:

```python
class RelativityOneFileEnumerator:
    def __init__(
        self,
        config: RelativityOneConfig,
        session: aiohttp.ClientSession,
        auth: RelativityOneAuthManager,
        rate_guard: KeplerRateLimitGuard,
    ):
        self._config = config
        self._session = session
        self._auth = auth
        self._rate_guard = rate_guard
        self._volume_tracker = _VolumeTracker(
            prefix=config.volume_prefix,
            max_size_gb=config.volume_max_size_gb,
        )

    async def enumerate(self, cancellation_event: asyncio.Event) -> AsyncIterator[CloudFileDescriptor]:
        ...
```

The artifact enforces a group contiguity guarantee: all `CloudFileDescriptor` objects for a document must be yielded contiguously so ECUBE can preserve document-level transactional integrity on the target media.

The enumerator handles:

- Folder, saved search, and production query sources
- Pagination using Object Manager `start` and `length`
- Per-document file discovery using Document File Manager
- Mapping Relativity file types to ECUBE SDK `FileType`
- Volume and subdirectory tracking for Relativity-style export layout
- Optional hash extraction from a configured workspace field

Representative target path layout:

```text
VOL001/NATIVES/001/file.docx
VOL001/NATIVES/002/file.pdf
VOL002/IMAGES/001/page_0001.tiff
```

## 6. File Downloading - downloader.py

### 6.1 RelativityOneFileStream and RelativityOneFileDownloader

The download layer implements `CloudFileStream` by wrapping an `aiohttp.ClientResponse` stream. Data is read in chunks and exposed as an async iterator that the Cloud Copy Engine can pipe directly to USB.

Representative classes:

```python
class RelativityOneFileStream(CloudFileStream):
    def __init__(self, descriptor: CloudFileDescriptor, response: aiohttp.ClientResponse, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self._descriptor = descriptor
        self._response = response
        self._chunk_size = chunk_size
        self._bytes_read = 0
        self._closed = False

    async def read(self, size: int = -1) -> bytes:
        ...

    async def close(self) -> None:
        ...


class RelativityOneFileDownloader:
    async def open_stream(self, descriptor: CloudFileDescriptor, cancellation_event: asyncio.Event) -> RelativityOneFileStream:
        ...
```

The provider chooses the correct endpoint based on the file descriptor.

- Native files: `documents/{documentId}/native-file`
- Images, PDFs, and other non-native assets: `files/{fileGuid}`

Artifact design decision: the rate-guard slot is released after response headers are received, not after full stream consumption, because Relativity rate limits requests rather than transferred bytes.

## 7. Error Classification - error_mapping.py

### 7.1 RelativityOneErrorClassifier

The error classifier maps provider failures to the ECUBE `CloudErrorClassification` taxonomy and must never raise itself. If classification fails, it returns `UNKNOWN`.

Representative conditions from the artifact:

| Source | Condition | Category | Retryable |
|---|---|---|---|
| HTTP | 401 Unauthorized | AUTHENTICATION | No |
| HTTP | 403 Forbidden | PERMANENT | No |
| HTTP | 404 Not Found | PERMANENT | No |
| HTTP | 429 Too Many Requests | RATE_LIMITED | Yes |
| HTTP | 500 / 502 / 503 / 504 | TRANSIENT | Yes |
| aiohttp | ClientConnectionError | TRANSIENT | Yes |
| aiohttp | ClientPayloadError | TRANSIENT | Yes |
| asyncio | TimeoutError | TRANSIENT | Yes |
| asyncio | CancelledError | PERMANENT | No |
| Any | Unrecognized exception | UNKNOWN | No |

The artifact explicitly treats classification as a best-effort safety path: if classification logic fails, the original error is wrapped into an `UNKNOWN` classification rather than propagating a secondary exception.

## 8. Metadata Resolution - metadata.py

### 8.1 RelativityOneMetadataResolver

The metadata resolver performs pre-flight validation by querying Object Manager for verified metadata such as file size and optional hashes before downloads are committed to USB.

Representative responsibilities:

- Group descriptors by document using `group_id`
- Query Object Manager for the related artifact IDs
- Return `CloudFileMetadata` for each input descriptor
- Mark unavailable descriptors explicitly when metadata cannot be resolved
- Normalize raw hash fields into `md5:` or `sha256:` prefixed values when possible

Representative structure:

```python
class RelativityOneMetadataResolver:
    def __init__(
        self,
        config: RelativityOneConfig,
        session: aiohttp.ClientSession,
        auth: RelativityOneAuthManager,
        rate_guard: KeplerRateLimitGuard,
    ):
        ...

    async def resolve(self, descriptors: list[CloudFileDescriptor]) -> list[CloudFileMetadata]:
        ...
```

## 9. The Main Provider - provider.py

### 9.1 RelativityOneProvider

`RelativityOneProvider` is the top-level `ICloudProvider` implementation. ECUBE interacts only with this class, which wires together configuration parsing, HTTP session management, authentication, rate limiting, enumeration, download streaming, metadata resolution, and error classification.

Representative skeleton:

```python
@provider_registry.register
class RelativityOneProvider(ICloudProvider):
    @property
    def provider_id(self) -> str:
        return "relativity_one"

    @property
    def display_name(self) -> str:
        return "RelativityOne"

    @property
    def capabilities(self) -> CloudProviderCapabilities:
        ...

    async def initialize(self, config: CloudProviderConfig) -> None:
        ...

    async def authenticate(self) -> AuthenticationResult:
        ...

    async def enumerate_files(self, cancellation_event: asyncio.Event) -> AsyncIterator[CloudFileDescriptor]:
        ...

    async def download_file(self, file_descriptor: CloudFileDescriptor, cancellation_event: asyncio.Event) -> CloudFileStream:
        ...

    async def resolve_metadata(self, file_descriptors: list[CloudFileDescriptor]) -> list[CloudFileMetadata]:
        ...

    def classify_error(self, error: Exception) -> CloudErrorClassification:
        ...

    async def shutdown(self) -> None:
        ...
```

The capability profile in the artifact includes:

- `supports_hash` depends on whether a hash field is configured
- `supports_file_size=True`
- `supports_streaming=True`
- `supports_resumable_download=False`
- `supports_concurrent_downloads=True`
- `supports_server_side_enumeration=True`
- `supports_groups=True`
- `supports_metadata_export=True`
- `rate_limited=True`

Initialization flow from the artifact:

1. Parse provider-specific settings into `RelativityOneConfig`.
2. Create a shared `aiohttp.ClientSession` with connection pooling.
3. Initialize the auth manager and inject credentials.
4. Initialize the rate limiter.
5. Initialize the enumerator.
6. Initialize the downloader.
7. Initialize the metadata resolver.

## 10. Provider Registration - __init__.py

The package auto-registers the provider when imported.

Representative module contents:

```python
"""ECUBE Cloud Provider Plugin: RelativityOne."""

from .provider import RelativityOneProvider

__all__ = ["RelativityOneProvider"]
__version__ = "1.0.0"
__ecube_provider_id__ = "relativity_one"
```

### 10.1 Auto-Registration Mechanism

The artifact describes two discovery mechanisms.

- Entry points, which are preferred. The provider is exposed under the `ecube.providers` entry point group.
- Package scanning as a fallback for installed packages matching the `ecube_provider_*` naming convention.

Representative entry point configuration:

```toml
[project.entry-points."ecube.providers"]
relativity_one = "ecube_provider_relativity:RelativityOneProvider"
```

## 11. Testing Strategy

### 11.1 Test Fixtures - conftest.py

The artifact defines shared fixtures for provider tests, including a mock aiohttp server that simulates OAuth2 token issuance, Object Manager queries, file info responses, and native file downloads.

Fixture responsibilities:

- Provide sample token, query, and file payloads
- Create a mock server with RelativityOne-like routes
- Build reusable `CloudProviderConfig` objects for tests
- Supply a reusable cancellation event for async flows

### 11.2 Key Test Cases

The guide lists 20 critical tests.

| # | Test Function | What It Validates |
|---|---|---|
| 1 | `test_full_lifecycle` | Complete initialize -> authenticate -> enumerate -> download -> shutdown flow |
| 2 | `test_enumerate_folder_with_subfolders` | Folder enumeration with pagination across multiple pages |
| 3 | `test_enumerate_saved_search` | Saved search payload generation |
| 4 | `test_enumerate_production` | Production query condition generation |
| 5 | `test_download_native_file` | Native-file streaming end to end |
| 6 | `test_download_image_file` | Image download by file GUID |
| 7 | `test_group_contiguity` | Contiguous grouping for multi-file documents |
| 8 | `test_rate_limit_429_backoff` | Backoff and retry behavior after `429` |
| 9 | `test_token_expiry_refresh` | Transparent token refresh during enumeration |
| 10 | `test_token_refresh_failure` | Escalation after failed refresh |
| 11 | `test_document_not_found_404` | Graceful handling of file-info `404` |
| 12 | `test_server_error_500_retry` | Classification of server failures as transient |
| 13 | `test_cancellation_during_enumeration` | Clean shutdown when cancelled during enumeration |
| 14 | `test_cancellation_during_download` | Graceful stream close during cancellation |
| 15 | `test_invalid_config_missing_workspace` | Validation failure for missing workspace ID |
| 16 | `test_concurrent_downloads` | Parallel download behavior |
| 17 | `test_metadata_resolution_with_hash` | Verified hash formatting |
| 18 | `test_metadata_resolution_without_hash` | Metadata resolution without hashes |
| 19 | `test_volume_rotation` | Volume increment when size thresholds are exceeded |
| 20 | `test_subdirectory_rotation` | Subdirectory rotation after file-count thresholds |

### 11.3 Representative Full Tests

The artifact includes full implementations for at least these core tests.

```python
@pytest.mark.asyncio
async def test_full_lifecycle(mock_server, make_config, cancellation_event):
    provider = RelativityOneProvider()
    config = make_config(source_type="folder")
    await provider.initialize(config)
    auth_result = await provider.authenticate()
    assert auth_result.success is True
    descriptors = []
    async for desc in provider.enumerate_files(cancellation_event):
        descriptors.append(desc)
    first = descriptors[0]
    stream = await provider.download_file(first, cancellation_event)
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    await stream.close()
    await provider.shutdown()
```

```python
@pytest.mark.asyncio
async def test_rate_limit_429_backoff(mock_server, make_config, cancellation_event):
    guard = KeplerRateLimitGuard(backoff_multiplier=1.0)
    guard.set_concurrency(2)
    start = time.monotonic()
    await guard.record_rate_limited(retry_after_seconds=1.0)
    await guard.acquire()
    elapsed = time.monotonic() - start
    guard.release()
    assert elapsed >= 0.9
```

```python
@pytest.mark.asyncio
async def test_cancellation_during_enumeration(mock_server, make_config):
    provider = RelativityOneProvider()
    config = make_config()
    await provider.initialize(config)
    await provider.authenticate()
    cancel = asyncio.Event()
    descriptors = []
    async for desc in provider.enumerate_files(cancel):
        descriptors.append(desc)
        if len(descriptors) == 1:
            cancel.set()
    await provider.shutdown()
```

## 12. Deployment and Configuration

### 12.1 Installation

Production installation from the artifact:

```bash
pip install ecube-provider-relativity
```

Development installation from the artifact:

```bash
git clone https://github.com/ecube/provider-relativity.git
cd provider-relativity
pip install -e ".[dev]"
```

The `[dev]` extra includes `pytest`, `pytest-asyncio`, `aiohttp[speedups]`, and `mypy`.

### 12.2 ECUBE Job Configuration Example

Representative configuration from the artifact:

```json
{
  "job_id": "JOB-2026-0501-001",
  "provider_id": "relativity_one",
  "target_devices": ["USB-A1", "USB-A2"],
  "provider_settings": {
    "instance_url": "https://myinstance.relativity.one",
    "workspace_id": 1018234,
    "source_type": "saved_search",
    "source_artifact_id": 1039567,
    "view_id": 1003684,
    "export_file_types": ["native", "image"],
    "include_subfolders": true,
    "hash_field_artifact_id": 1042890,
    "control_number_field_id": 1003667,
    "additional_field_ids": [1003667, 1040100],
    "page_size": 500,
    "max_concurrent_api_requests": 4,
    "download_timeout_seconds": 300,
    "download_chunk_size": 262144,
    "rate_limit_backoff_multiplier": 1.5,
    "generate_load_file": true,
    "app_guid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "volume_prefix": "VOL",
    "volume_max_size_gb": 4.0,
    "native_subdirectory_prefix": "NATIVES",
    "image_subdirectory_prefix": "IMAGES"
  },
  "credential_settings": {
    "grant_type": "client_credentials",
    "client_id": "your-oauth2-client-id",
    "client_secret": "your-oauth2-client-secret",
    "token_url": "https://myinstance.relativity.one/Relativity/Identity/connect/token"
  }
}
```

### 12.3 RelativityOne Prerequisites

The artifact requires these prerequisites in the target RelativityOne environment:

- OAuth2 client registration using the Client Credentials grant type
- A service account with document view permission, export permission, and REST API access
- Folder visibility for folder-based exports
- An optional workspace hash field if pre-flight hash validation is required
- An optional registered application GUID if `X-Kepler-Referrer` tracking is desired

## 13. Operational Runbook

### 13.1 Common Issues and Resolution

| Symptom | Likely Cause | Resolution |
|---|---|---|
| AUTHENTICATION error on startup | Invalid client credentials | Verify OAuth2 client ID and secret and ensure the client is enabled |
| CONFIGURATION error: Workspace not found | Incorrect `workspace_id` | Verify the workspace artifact ID in RelativityOne |
| Frequent RATE_LIMITED events | Too many concurrent requests | Reduce `max_concurrent_api_requests` or increase `rate_limit_backoff_multiplier` |
| PERMANENT error: 403 on file download | Insufficient permissions | Verify document view and export permissions for the service account |
| Slow enumeration | Large document set plus throttling | Increase `page_size` and reduce `additional_field_ids` |
| Hash validation failures | Hash field not populated | Verify Relativity processing and `hash_field_artifact_id` configuration |
| Volume numbering jumps | Files exceed `volume_max_size_gb` | Increase the threshold or accept multi-volume output |
| Missing images in output | Images not configured | Add `"image"` to `export_file_types` |
| Timeout during download | Large file plus slow connection | Increase `download_timeout_seconds` |
| Empty enumeration results | Saved search returns no documents | Verify saved search contents and `view_id` field coverage |

### 13.2 Logging and Diagnostics

The provider uses Python's standard logging hierarchy under the `ecube_provider_relativity` namespace.

| Logger Name | Component |
|---|---|
| `ecube_provider_relativity` | Root logger for provider events |
| `ecube_provider_relativity.auth` | Token acquisition, refresh, and failures |
| `ecube_provider_relativity.enumerator` | Enumeration queries, pagination, and document counts |
| `ecube_provider_relativity.downloader` | Stream open, read, and close lifecycle |
| `ecube_provider_relativity.rate_limiter` | Rate-limit budget tracking and cooldowns |
| `ecube_provider_relativity.metadata` | Metadata resolution and availability checks |

Log-level guidance from the artifact:

- `DEBUG`: request and response headers without secrets, query payloads, rate-limit header values, stream chunk counts
- `INFO`: job start and completion, authentication success, totals, progress milestones, volume and subdirectory transitions
- `WARNING`: rate-limit backoffs, proactive refresh, retryable failures, missing native files
- `ERROR`: permanent failures, configuration errors, authentication failures, and unclassified exceptions

Security note from the artifact: the auth manager never logs the access token or client secret, even at `DEBUG`.

## 14. Appendix: RelativityOne Object Manager Query Reference

This appendix captures the example request and response bodies used by the enumerator.

### 14.1 Folder Query (with Subfolders)

Request body:

```json
{
  "objectType": {"artifactTypeID": 10},
  "fields": [
    {"ArtifactID": 1003667},
    {"ArtifactID": 1003668},
    {"ArtifactID": 1003669},
    {"ArtifactID": 1042890}
  ],
  "sorts": [{"FieldIdentifier": {"ArtifactID": 1003667}, "Order": 0, "Direction": 0}],
  "condition": "('Artifact ID' IN OBJECT 1039567)",
  "start": 1,
  "length": 500
}
```

Response body:

```json
{
  "TotalCount": 15234,
  "Objects": [
    {
      "ArtifactID": 1050001,
      "FieldValues": [
        {"Field": {"ArtifactID": 1003667, "Name": "Control Number"}, "Value": "REL-000001"},
        {"Field": {"ArtifactID": 1003668, "Name": "File Size"}, "Value": 524288},
        {"Field": {"ArtifactID": 1003669, "Name": "File Name"}, "Value": "Contract_Agreement_v3.docx"},
        {"Field": {"ArtifactID": 1042890, "Name": "MD5 Hash"}, "Value": "d41d8cd98f00b204e9800998ecf8427e"}
      ]
    },
    {
      "ArtifactID": 1050002,
      "FieldValues": [
        {"Field": {"ArtifactID": 1003667, "Name": "Control Number"}, "Value": "REL-000002"},
        {"Field": {"ArtifactID": 1003668, "Name": "File Size"}, "Value": 1048576},
        {"Field": {"ArtifactID": 1003669, "Name": "File Name"}, "Value": "Board_Minutes_2025-Q4.pdf"},
        {"Field": {"ArtifactID": 1042890, "Name": "MD5 Hash"}, "Value": "098f6bcd4621d373cade4e832627b4f6"}
      ]
    }
  ]
}
```

### 14.2 Saved Search Query

```json
{
  "objectType": {"artifactTypeID": 10},
  "fields": [
    {"ArtifactID": 1003667},
    {"ArtifactID": 1003668},
    {"ArtifactID": 1003669}
  ],
  "sorts": [{"FieldIdentifier": {"ArtifactID": 1003667}, "Order": 0, "Direction": 0}],
  "condition": "",
  "querySource": {"savedSearchID": 1039567},
  "start": 1,
  "length": 1000
}
```

The artifact notes that `querySource.savedSearchID` references the saved search artifact ID and requires `condition` to remain an empty string in this mode.

### 14.3 Production Query

```json
{
  "objectType": {"artifactTypeID": 10},
  "fields": [
    {"ArtifactID": 1003667},
    {"ArtifactID": 1003668},
    {"ArtifactID": 1003669}
  ],
  "sorts": [{"FieldIdentifier": {"ArtifactID": 1003667}, "Order": 0, "Direction": 0}],
  "condition": "('Production::Production Set' == OBJECT 1045890)",
  "start": 1,
  "length": 1000
}
```

### 14.4 Document File Manager File Info Response

```json
[
  {
    "Guid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "Filename": "Contract_Agreement_v3.docx",
    "Type": "Native",
    "Size": 524288,
    "DocumentArtifactID": 1050001
  },
  {
    "Guid": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "Filename": "REL-000001_001.tiff",
    "Type": "Image",
    "Size": 1048576,
    "DocumentArtifactID": 1050001
  },
  {
    "Guid": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "Filename": "REL-000001_002.tiff",
    "Type": "Image",
    "Size": 983040,
    "DocumentArtifactID": 1050001
  }
]
```

Each entry represents one downloadable file associated with a document. The `Guid` supports the `files/{fileGuid}` endpoint, while native files can also be fetched through `documents/{documentId}/native-file`.