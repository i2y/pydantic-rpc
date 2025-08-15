"""Olympics Agent example using Anthropic API with ASGIApp"""

from typing import Annotated, AsyncIterator
from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_rpc import Message, ASGIApp
import os


class CityLocation(Message):
    city: Annotated[str, Field(description="The city where the Olympics were held")]
    country: Annotated[
        str, Field(description="The country where the Olympics were held")
    ]


class OlympicsQuery(Message):
    year: Annotated[int, Field(description="The year of the Olympics", ge=1896)]

    def prompt(self):
        return f"Where were the Olympics held in {self.year}?"


class OlympicsDurationQuery(Message):
    start: Annotated[int, Field(description="The start year of the Olympics", ge=1896)]
    end: Annotated[int, Field(description="The end year of the Olympics", ge=1896)]

    def prompt(self):
        return f"From {self.start} to {self.end}, how many Olympics were held? Please provide the list of countries and cities."


class StreamingResult(Message):
    answer: Annotated[str, Field(description="The answer to the query")]


class OlympicsAgent:
    def __init__(self):
        # Use Anthropic API
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")

        anthropic_model = AnthropicModel(
            "claude-3-haiku-20240307",  # Using Haiku for faster responses
            api_key=api_key,
        )
        self._agent = Agent(anthropic_model)

    async def ask(self, req: OlympicsQuery) -> CityLocation:
        result = await self._agent.run(req.prompt(), result_type=CityLocation)
        return result.data

    async def ask_stream(
        self, req: OlympicsDurationQuery
    ) -> AsyncIterator[StreamingResult]:
        async with self._agent.run_stream(req.prompt(), result_type=str) as result:
            async for data in result.stream_text(delta=True):
                yield StreamingResult(answer=data)


# Create the ASGI application
app = ASGIApp()
app.mount(OlympicsAgent())


if __name__ == "__main__":
    import uvicorn
    import random

    port = random.randint(9000, 9999)
    print(f"Starting Olympics Agent ASGI server on http://localhost:{port}")
    print("Available endpoints:")
    print(
        "  POST /olympicsagent.v1.OlympicsAgent/ask        - Query single Olympics year"
    )
    print(
        "  POST /olympicsagent.v1.OlympicsAgent/ask_stream - Query Olympics range (streaming)"
    )
    print("\nExample curl commands:")
    print(
        f"  curl -X POST http://localhost:{port}/olympicsagent.v1.OlympicsAgent/ask \\"
    )
    print('    -H "Content-Type: application/json" \\')
    print("    -d '{\"year\": 2024}'")

    uvicorn.run(app, host="0.0.0.0", port=port)
