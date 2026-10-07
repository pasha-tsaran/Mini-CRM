from typing import TypeVar

from flask import Flask, jsonify
from pydantic import BaseModel, ValidationError
from werkzeug.exceptions import HTTPException

from app.services.leads import LeadNotFoundError
from app.services.telegram import IntegrationConflict


Schema = TypeVar("Schema", bound=BaseModel)


class RequestValidationError(Exception):
    """Ошибка входных данных, которую допустимо показать клиенту."""

    def __init__(self, validation: ValidationError) -> None:
        super().__init__("Некорректные входные данные")
        self.validation = validation


def validate_request(schema: type[Schema], data: object) -> Schema:
    """Отделить ошибки запроса от внутренних ошибок Pydantic в сервисах."""
    try:
        return schema.model_validate(data)
    except ValidationError as error:
        raise RequestValidationError(error) from error


FIELD_MESSAGES = {
    "missing": "Обязательное поле.",
    "string_type": "Значение должно быть строкой.",
    "string_too_short": "Поле не должно быть пустым.",
    "string_too_long": "Превышена допустимая длина поля.",
    "extra_forbidden": "Неизвестное поле.",
    "phone_format": "Используйте номер +7 и десять цифр или запись с начальной 8.",
    "literal_error": "Допустимые статусы: new, in_progress, closed, rejected.",
    "integer_required": "Укажите целое число без повторения параметра.",
    "greater_than_equal": "Значение меньше допустимого минимума.",
    "less_than_equal": "Значение больше допустимого максимума.",
    "model_type": "Тело запроса должно быть JSON-объектом.",
}
HTTP_ERRORS = {
    400: ("invalid_json", "Повреждённый JSON."),
    404: ("not_found", "Страница не найдена."),
    405: ("method_not_allowed", "Метод запроса не поддерживается."),
    415: ("unsupported_media_type", "Используйте Content-Type: application/json."),
}


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(IntegrationConflict)
    def integration_conflict(error):
        return jsonify(error={'code': 'integration_conflict', 'message': 'Повтор запроса не совпадает с исходным или код недействителен.'}), 409
    @app.errorhandler(RequestValidationError)
    def validation_error(error: RequestValidationError):
        details = [
            {
                "field": ".".join(str(part) for part in item["loc"]) or "body",
                "code": item["type"],
                "message": FIELD_MESSAGES.get(item["type"], "Недопустимое значение."),
            }
            for item in error.validation.errors(include_input=False, include_context=False, include_url=False)
        ]
        return jsonify(error={"code": "validation_error", "message": "Проверьте поля и параметры запроса.", "details": details}), 422

    @app.errorhandler(LeadNotFoundError)
    def lead_not_found(error: LeadNotFoundError):
        return jsonify(error={"code": "lead_not_found", "message": "Заявка не найдена."}), 404

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        code, message = HTTP_ERRORS.get(error.code, ("http_error", "Запрос не может быть обработан."))
        response = error.get_response()
        response.data = app.json.dumps({"error": {"code": code, "message": message}})
        response.content_type = "application/json"
        return response

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception):
        # Не пишем тела запросов, URL с токенами и SQL-параметры в журнал.
        app.logger.error("Непредвиденная ошибка обработки запроса: %s", type(error).__name__)
        return jsonify(error={"code": "internal_error", "message": "Внутренняя ошибка сервера."}), 500
