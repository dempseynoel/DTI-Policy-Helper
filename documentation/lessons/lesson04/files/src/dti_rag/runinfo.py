"""What is actually serving: model versions read from Azure at run time, not copied from notes.

Needs Reader on the Foundry resource (you, in dev; the deploy and eval identities in test).
"""

from __future__ import annotations

from dataclasses import dataclass

from dti_rag.clients import credential
from dti_rag.config import Settings


@dataclass(frozen=True)
class ServingModel:
    deployment: str
    model: str
    version: str
    sku: str
    capacity: int | None


def serving_models(settings: Settings) -> dict[str, ServingModel]:
    """Deployment name -> the model and version the Foundry resource says it is serving."""
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient

    subscription, group, account = settings.require(
        "azure_subscription_id", "azure_resource_group", "azure_foundry_account"
    )
    client = CognitiveServicesManagementClient(credential(), subscription)
    out: dict[str, ServingModel] = {}
    for d in client.deployments.list(group, account):
        model = d.properties.model
        out[d.name] = ServingModel(
            deployment=d.name,
            model=model.name,
            version=model.version,
            sku=d.sku.name if d.sku else "",
            capacity=d.sku.capacity if d.sku else None,
        )
    return out
