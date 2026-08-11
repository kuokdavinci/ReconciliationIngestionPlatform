"""Workflow control-plane adapters."""

from src.infrastructure.workflows.airflow import AirflowWorkflowGateway
from src.infrastructure.workflows.local import LocalWorkflowGateway

__all__ = ["AirflowWorkflowGateway", "LocalWorkflowGateway"]
