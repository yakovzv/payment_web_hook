import functools
from functools import wraps
from typing import List, Union

import pydantic
from pydantic import TypeAdapter, BaseModel
from psycopg2.extras import RealDictRow
from asyncpg import Record

from app.internal.repository.exceptions import EmptyResult

from .handle_exception import handle_exception


def collect_response(
    fn=None,
    convert_to_pydantic=True,
    nullable=False,
):
    # fn равно None, когда декоратору переданы параметры
    if fn is None:
        return functools.partial(
            collect_response,
            convert_to_pydantic=convert_to_pydantic,
            nullable=nullable,
        )

    @wraps(fn)
    @handle_exception
    async def inner(*args: object, **kwargs: object) -> Union[List[BaseModel], BaseModel, None]:
        response = await fn(*args, **kwargs)

        if response is True:
            return response

        if response is None:
            # некоторые ответы — пустые списки, их надо разрешать.
            # isinstance не понимает List[int], только List, поэтому берём __origin__

            if "return" in fn.__annotations__:
                return_class = fn.__annotations__["return"]
                if hasattr(return_class, "__origin__"):
                    return_class = return_class.__origin__
                if isinstance([], return_class):
                    return []
                if nullable:
                    return None

            raise EmptyResult

        if convert_to_pydantic:
            ann = fn.__annotations__["return"]
            json = __convert_response(response, annotations=str(ann))
            ta = TypeAdapter(ann)
            data = ta.validate_python(json)
            return data
        return response

    return inner


def __convert_response(response: Record | List[Record], annotations: str):
    if annotations.replace("typing.", "").startswith("List"):
        if not isinstance(response, List):
            raise TypeError("В аннотации указан список, получена одна запись")
        return [__convert_record(item) for item in response]
    return __convert_record(response)


def __convert_record(r: Record):
    result = {}
    for key, value in r.items():
        result[key] = value
    return result
