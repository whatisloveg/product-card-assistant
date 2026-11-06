import pytest
from pydantic import ValidationError

from card_assistant.models import ProductInput


def test_specs_values_are_normalized():
    product = ProductInput(name=" Манометр ", specs={" класс точности ": 1.5, "диаметр": 100, "пусто": None, "": "x"})
    assert product.name == "Манометр"
    assert product.specs == {"класс точности": "1.5", "диаметр": "100", "пусто": ""}
    assert product.empty_specs == ["пусто"]


def test_null_fields_become_empty():
    product = ProductInput(name="Манометр", manufacturer=None, description=None, specs=None)
    assert product.empty_fields() == ["Производитель", "Описание / фрагмент паспорта"]
    assert not product.has_enough_data()


@pytest.mark.parametrize("payload", [{}, {"name": "   "}, {"name": "Манометр", "specs": ["диапазон"]}])
def test_invalid_input_is_rejected(payload):
    with pytest.raises(ValidationError):
        ProductInput.model_validate(payload)


def test_invalid_json_is_rejected():
    with pytest.raises(ValidationError):
        ProductInput.model_validate_json('{"name": "Манометр",')
