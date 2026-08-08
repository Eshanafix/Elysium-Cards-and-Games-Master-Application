"""
Declarative report catalog (LLD section 20.4/20.5; docs/IMPLEMENTATION_
PLAN.md section 1) tying report_service's query functions to the Reports
screen's picker/filter/preview/export UI. One entry per LLD 20.5 CSV
dataset -- `columns` doubles as both the preview table's header order and
the CSV export's field order.
"""

from dataclasses import dataclass
from typing import Callable

from elysium.services import report_service


@dataclass
class ReportDefinition:
    key: str
    label: str
    columns: list[str]
    fetch: Callable
    admin_only: bool = False
    supports_streamer_filter: bool = False
    supports_product_filter: bool = False
    supports_date_range: bool = False

    def run(self, user, streamer_id=None, product_id=None, start_date=None, end_date=None) -> list[dict]:
        kwargs = {}
        if self.supports_streamer_filter:
            kwargs["streamer_id"] = streamer_id
        if self.supports_product_filter:
            kwargs["product_id"] = product_id
        if self.supports_date_range:
            kwargs["start_date"] = start_date
            kwargs["end_date"] = end_date
        return self.fetch(user, **kwargs)


REPORT_DEFINITIONS: list[ReportDefinition] = [
    ReportDefinition(
        key="master_inventory",
        label="Master Inventory",
        columns=["product_id", "product_name", "set_name", "booster_type", "total_packs", "unassigned_packs", "assigned_packs", "resolved_pack_price", "price_status"],
        fetch=report_service.master_inventory_report,
        admin_only=True,
    ),
    ReportDefinition(
        key="streamer_inventory",
        label="Streamer Inventory",
        columns=["streamer_username", "product_id", "product_name", "current_packs", "resolved_pack_price", "price_status"],
        fetch=report_service.streamer_inventory_report,
        supports_streamer_filter=True,
    ),
    ReportDefinition(
        key="streamer_allocations",
        label="Streamer Allocations",
        columns=["streamer_username", "product_id", "product_name", "current_packs"],
        fetch=report_service.streamer_allocations_report,
        admin_only=True,
        supports_streamer_filter=True,
    ),
    ReportDefinition(
        key="streams",
        label="Streams",
        columns=["stream_id", "streamer_username", "date", "start_time", "end_time", "status", "number_of_breaks", "sum_of_break_gross", "final_stream_gross", "gross_difference", "stream_pack_market_value", "stream_profit", "stream_profit_margin", "notes", "force_canceled", "correction_count"],
        fetch=report_service.streams_report,
        supports_streamer_filter=True,
        supports_date_range=True,
    ),
    ReportDefinition(
        key="breaks",
        label="Breaks",
        # streamer_username/sequence_number/status/packs_opened first --
        # that's what you actually look at; break_id/stream_id (long UUIDs)
        # moved to the end so they don't dominate the row.
        columns=["streamer_username", "sequence_number", "name", "status", "packs_opened", "start_time", "end_time", "total_pack_market_value", "break_gross", "break_profit", "break_profit_margin", "notes", "updated_at", "break_id", "stream_id"],
        fetch=report_service.breaks_report,
        supports_streamer_filter=True,
        supports_date_range=True,
    ),
    ReportDefinition(
        key="break_products",
        label="Break Products",
        columns=["streamer_username", "product_name", "quantity", "locked_unit_price", "price_source", "line_market_value", "product_id", "break_id", "stream_id"],
        fetch=report_service.break_products_report,
        supports_streamer_filter=True,
        supports_date_range=True,
    ),
    ReportDefinition(
        key="stream_profit",
        label="Stream Profit",
        columns=["stream_id", "streamer_username", "date", "final_stream_gross", "stream_pack_market_value", "stream_profit", "stream_profit_margin"],
        fetch=report_service.stream_profit_report,
        supports_streamer_filter=True,
        supports_date_range=True,
    ),
    ReportDefinition(
        key="break_profit",
        label="Break Profit",
        columns=["break_id", "stream_id", "streamer_username", "sequence_number", "break_gross", "total_pack_market_value", "break_profit", "break_profit_margin"],
        fetch=report_service.break_profit_report,
        supports_streamer_filter=True,
        supports_date_range=True,
    ),
    ReportDefinition(
        key="price_current",
        label="Current Prices",
        columns=["product_id", "product_name", "resolved_pack_price", "resolved_price_source", "price_status", "raw_loose_pack_market_price", "raw_box_market_price", "last_successful_refresh_at"],
        fetch=report_service.price_current_report,
    ),
    ReportDefinition(
        key="price_history",
        label="Price History",
        columns=["product_id", "product_name", "previous_price", "new_price", "previous_source", "new_source", "initiated_by", "manual_entry_by", "timestamp", "tcgcsv_status"],
        fetch=report_service.price_history_report,
        supports_product_filter=True,
    ),
    ReportDefinition(
        key="inventory_audit",
        label="Inventory Audit",
        columns=["event_id", "action_type", "performed_by", "role", "timestamp", "product_id", "streamer_username", "quantity_change", "reason", "status"],
        fetch=report_service.inventory_audit_report,
        admin_only=True,
        supports_streamer_filter=True,
        supports_date_range=True,
    ),
    ReportDefinition(
        key="inventory_discrepancies",
        label="Inventory Discrepancies",
        columns=["discrepancy_id", "streamer_username", "product_name", "type", "quantity", "source", "status", "created_at", "resolved_at", "resolution_note"],
        fetch=report_service.inventory_discrepancies_report,
        supports_streamer_filter=True,
    ),
    ReportDefinition(
        key="users",
        label="Users",
        columns=["user_id", "username", "roles", "is_active", "decommission_status", "created_at", "disabled_at"],
        fetch=report_service.users_report,
        admin_only=True,
    ),
    ReportDefinition(
        key="decommission_requests",
        label="Decommission Requests",
        columns=["request_id", "streamer_username", "status", "initiated_by", "initiated_at", "approved_by", "approved_at", "notes"],
        fetch=report_service.decommission_requests_report,
        admin_only=True,
    ),
]


def available_reports(user) -> list[ReportDefinition]:
    from elysium.models.users import ROLE_ADMIN

    if ROLE_ADMIN in user.roles:
        return REPORT_DEFINITIONS

    return [r for r in REPORT_DEFINITIONS if not r.admin_only]
