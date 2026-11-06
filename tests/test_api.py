import pytest
from fastapi.testclient import TestClient

from card_assistant.api import app, get_service
from card_assistant.llm import LLMError
from card_assistant.service import CardService

from .conftest import FakeLLM

VALID = {
    "name": "Манометр показывающий DM 02",
    "manufacturer": "Манотомь",
    "specs": {"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5", "присоединение": "G1/2",
              "диаметр корпуса": "100 мм"},
    "description": "Прибор предназначен для измерения избыточного давления...",
}


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use_service(service) -> None:
    app.dependency_overrides[get_service] = lambda: service


def test_card_is_returned_in_three_formats(client, make_draft, settings):
    use_service(CardService(FakeLLM([make_draft()]), settings))
    response = client.post("/api/cards", json=VALID)
    assert response.status_code == 200
    body = response.json()
    assert body["card"]["seo_title"].startswith("Манометр DM 02")
    assert "## Характеристики" in body["markdown"]
    assert "ХАРАКТЕРИСТИКИ" in body["text"]


def test_broken_json_gets_readable_error(client):
    response = client.post("/api/cards", content='{"name": "Манометр",', headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["details"][0].startswith("некорректный JSON")


def test_wrong_field_types_are_explained(client):
    response = client.post("/api/cards", json={"name": "", "specs": ["диапазон"]})
    assert response.status_code == 422
    details = response.json()["details"]
    assert "name: не может быть пустым" in details
    assert any(d.startswith("specs: ожидается объект") for d in details)


def test_insufficient_data_lists_missing_fields(client, settings):
    use_service(CardService(FakeLLM([]), settings))
    response = client.post("/api/cards", json={"name": "Манометр"})
    assert response.status_code == 422
    assert response.json()["missing"]


def test_llm_error_is_reported(client):
    class FailingService:
        def generate(self, product):
            raise LLMError("Нет соединения с Anthropic.", 503)

    use_service(FailingService())
    response = client.post("/api/cards", json=VALID)
    assert response.status_code == 503
    assert response.json() == {"error": "Нет соединения с Anthropic."}


def test_examples_and_form_are_served(client):
    assert client.get("/").status_code == 200
    examples = client.get("/api/examples").json()
    assert [e["id"] for e in examples] == ["01_dm02", "02_pd100", "03_incomplete", "04_injection"]
