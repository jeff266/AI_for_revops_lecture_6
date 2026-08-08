from abc import ABC, abstractmethod
from typing import List, Optional


class StorageAdapter(ABC):
    """
    Contract for all storage adapters. Supabase today;
    Snowflake/BigQuery/Postgres later implement the same
    interface. This is the API between the nightly agent,
    the CRO query agent, and whatever runs the ETL.
    """

    @abstractmethod
    def upsert_deal(self, deal: dict) -> None:
        """Write or update a deal record."""

    @abstractmethod
    def upsert_call(self, call: dict, company_name: str) -> None:
        """Write or update a call record."""

    @abstractmethod
    def insert_analysis(self, deal_id: str, company_name: str,
                        scores: dict, analysis_content: str,
                        output_file: str = '') -> None:
        """Insert one analysis row. scores includes
        component_scores (JSONB-ready dict) and, when the
        methodology is MEDDICC, the seven legacy score columns."""

    @abstractmethod
    def query(self, sql: str, params: Optional[dict] = None
             ) -> List[dict]:
        """Execute a read query, return list of dicts."""

    def test_connection(self) -> bool:
        """Optional override. Default: True."""
        return True
