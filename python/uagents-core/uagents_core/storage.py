import base64
import struct
from datetime import datetime
from secrets import token_bytes

import requests

from uagents_core.config import AgentverseConfig
from uagents_core.identity import Identity


def compute_attestation(
    identity: Identity, validity_start: datetime, validity_secs: int, nonce: bytes
) -> str:
    """
    Compute a valid agent attestation token for authentication.
    """
    assert len(nonce) == 32, "Nonce is of invalid length"

    valid_from = int(validity_start.timestamp())
    valid_to = valid_from + validity_secs

    public_key = bytes.fromhex(identity.pub_key)

    payload = public_key + struct.pack(">QQ", valid_from, valid_to) + nonce
    assert len(payload) == 81, "attestation payload is incorrect"

    signature = identity.sign(payload)
    attestation = f"attr:{base64.b64encode(payload).decode()}:{signature}"
    return attestation


class ExternalStorage:
    def __init__(
        self,
        *,
        identity: Identity | None = None,
        storage_url: str | None = None,
        api_token: str | None = None,
    ):
        self.identity = identity
        self.api_token = api_token
        if not (identity or api_token):
            raise ValueError(
                "Either an identity or an API token must be provided for authentication"
            )
        self.storage_url = storage_url or AgentverseConfig().storage_endpoint

    def _make_attestation(self) -> str:
        nonce = token_bytes(32)
        now = datetime.now()
        if not self.identity:
            raise RuntimeError("No identity available to create attestation")
        return compute_attestation(
            identity=self.identity,
            validity_start=now,
            validity_secs=3600,
            nonce=nonce,
        )

    def _get_auth_header(self) -> dict:
        if self.api_token:
            return {"Authorization": f"Bearer {self.api_token}"}
        if self.identity:
            return {"Authorization": f"Agent {self._make_attestation()}"}
        raise RuntimeError("No identity or API token available for authentication")

    def upload(
        self,
        asset_id: str,
        asset_content: bytes,
        mime_type: str = "text/plain",
    ) -> dict:
        url = f"{self.storage_url}/assets/{asset_id}/contents/"
        headers = self._get_auth_header()
        headers["Content-Type"] = "application/json"
        payload = {
            "contents": base64.b64encode(asset_content).decode(),
            "mime_type": mime_type,
        }
        response = requests.put(
            url=url,
            json=payload,
            headers=headers,
            timeout=10,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Upload failed: {response.status_code}, {response.text}"
            )

        return response.json()

    def download(self, asset_id: str) -> dict:
        url = f"{self.storage_url}/assets/{asset_id}/contents/"
        headers = self._get_auth_header()
        response = requests.get(
            url=url,
            headers=headers,
            timeout=10,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Download failed: {response.status_code}, {response.text}"
            )

        return response.json()

    def create_asset(
        self,
        name: str,
        content: bytes,
        mime_type: str = "text/plain",
        lifetime_hours: int = 24,
    ) -> str:
        if not self.api_token:
            raise RuntimeError("API token required to create assets")
        url = f"{self.storage_url}/assets/"
        headers = self._get_auth_header()
        headers["Content-Type"] = "application/json"
        payload = {
            "name": name,
            "mime_type": mime_type,
            "contents": base64.b64encode(content).decode(),
            "lifetime_hours": lifetime_hours,
        }

        response = requests.post(
            url=url,
            json=payload,
            headers=headers,
            timeout=10,
        )
        if response.status_code != 201:
            raise RuntimeError(
                f"Asset creation failed: {response.status_code}, {response.text}"
            )

        return response.json()["asset_id"]

    def set_permissions(
        self, asset_id: str, agent_address: str, read: bool = True, write: bool = True
    ) -> dict:
        if not self.api_token:
            raise RuntimeError("API token required to set permissions")
        url = f"{self.storage_url}/assets/{asset_id}/permissions/"
        headers = self._get_auth_header()
        headers["Content-Type"] = "application/json"
        payload = {
            "agent_address": agent_address,
            "read": read,
            "write": write,
        }

        response = requests.put(
            url=url,
            json=payload,
            headers=headers,
            timeout=10,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Set permissions failed: {response.status_code}, {response.text}"
            )

        return response.json()
