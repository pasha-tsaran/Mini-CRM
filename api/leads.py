from flask import Blueprint, current_app, jsonify, request

from app.errors import validate_request
from app.schemas.lead import LeadCreate, LeadPagination, LeadStatusUpdate
from app.services import leads as service
from app.services.statistics import get_statistics
from database.session import get_session


blueprint = Blueprint("leads", __name__)


@blueprint.get("/stats")
def statistics():
    return jsonify(get_statistics(get_session()))


@blueprint.post("/lead")
def create_lead():
    data = validate_request(LeadCreate, request.get_json())
    username = current_app.config.get('TELEGRAM_BOT_USERNAME') if current_app.config.get('CRM_BOT_API_TOKEN') else None
    result = service.create_lead(get_session(), data, bot_username=username)
    response = jsonify(result.model_dump(mode="json"))
    response.headers['Cache-Control'] = 'no-store'
    return response, 201


@blueprint.get("/leads")
def list_leads():
    # Повторяющиеся параметры не должны незаметно терять значения.
    arguments = {key: values[0] if len(values) == 1 else values for key, values in request.args.lists()}
    pagination = validate_request(LeadPagination, arguments)
    result = service.list_leads(get_session(), pagination)
    return jsonify(result.model_dump(mode="json"))


@blueprint.patch("/lead/<int:lead_id>/status")
def update_status(lead_id: int):
    data = validate_request(LeadStatusUpdate, request.get_json())
    result = service.update_status(get_session(), lead_id, data)
    return jsonify(result.model_dump(mode="json"))
