from datetime import datetime

from flask import Blueprint, current_app, render_template, request

from app.errors import validate_request
from app.schemas.lead import LeadPagination
from app.services.leads import list_leads
from app.services.notifications import STATUS_LABELS
from app.services.statistics import get_statistics
from app.services.telegram import delivery_overview
from database.session import get_session


blueprint = Blueprint("views", __name__)

@blueprint.app_template_filter("local_date")
def local_date(value: datetime) -> str:
    return value.astimezone(current_app.extensions["ui_timezone"]).strftime("%d.%m.%Y %H:%M")


@blueprint.get("/")
def leads_page():
    arguments = {key: values[0] if len(values) == 1 else values for key, values in request.args.lists()}
    pagination = validate_request(LeadPagination, arguments)
    session = get_session()
    page = list_leads(session, pagination)
    statistics = get_statistics(session)
    channels = delivery_overview(session, [lead.id for lead in page.items])
    return render_template(
        "leads.html", page=page, statistics=statistics, status_labels=STATUS_LABELS,
        channels=channels,
        timezone=current_app.config["UI_TIMEZONE"],
        previous_offset=max(0, page.offset - page.limit),
        next_offset=page.offset + page.limit,
        page_number=page.offset // page.limit + 1,
        page_count=max(1, (page.total + page.limit - 1) // page.limit),
    )
