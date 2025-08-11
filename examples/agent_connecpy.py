import asyncio

from typing import Annotated

from hypercorn.asyncio import serve
from hypercorn.config import Config
from openai import AsyncOpenAI
from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_rpc import ASGIApp, Message


class CityLocation(Message):
    city: Annotated[str, Field(description="The city where the Olympics were held")]
    country: Annotated[
        str, Field(description="The country where the Olympics were held")
    ]


class Olympics(Message):
    year: Annotated[
        int, Field(description="The year of the Olympics", ge=1896, multiple_of=4)
    ]

    def prompt(self):
        return f"Where were the Olympics held in {self.year}?"


class OlympicsLocationAgent:
    def __init__(self):
        client = AsyncOpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama_api_key",
        )
        ollama_model = OpenAIModel(
            model_name="llama3.2",
            openai_client=client,
        )
        self._agent = Agent(ollama_model, result_type=CityLocation)

    async def ask(self, req: Olympics) -> CityLocation:
        result = await self._agent.run(req.prompt())
        return result.data


async def main():
    app = ASGIApp()
    app.mount(OlympicsLocationAgent())
    config = Config()
    config.bind = ["0.0.0.0:3000"]
    await serve(app, config)


if __name__ == "__main__":
    asyncio.run(main())
