import hmac

from flask import Blueprint, current_app, jsonify, request

from app.errors import validate_request
from app.schemas.lead import LeadCreate
from app.schemas.telegram import TelegramBinding, TelegramLead
from app.services.leads import create_lead
from app.services.telegram import bind_telegram
from database.session import get_session


blueprint = Blueprint('telegram', __name__, url_prefix='/integrations/telegram')


@blueprint.before_request
def authorize():
    expected = current_app.config.get('CRM_BOT_API_TOKEN', '')
    provided = request.headers.get('Authorization', '')
    if not expected or not hmac.compare_digest(provided.encode(), f'Bearer {expected}'.encode()):
        return jsonify(error={'code': 'unauthorized', 'message': 'Требуется авторизация интеграции.'}), 401


@blueprint.post('/leads')
def create():
    data = validate_request(TelegramLead, request.get_json())
    fields = LeadCreate(**data.model_dump(include={'name', 'phone', 'message'}))
    result = create_lead(get_session(), fields, telegram=data)
    return jsonify(result.model_dump(mode='json')), 201


@blueprint.post('/bind')
def bind():
    data = validate_request(TelegramBinding, request.get_json())
    return jsonify(bind_telegram(get_session(), data))
