from datetime import datetime
from typing import Any

from pydantic import BaseModel

from uagents import Agent
from uagents.experimental.mobility.protocols.base_protocol import (
    CheckIn,
    CheckOut,
    Location,
    MobilityType,
)
from uagents.experimental.search import Agent as SearchResultAgent
from uagents.experimental.search import geosearch_agents_by_proximity
from uagents.types import AgentGeolocation


class MobilityMetadata(BaseModel):
    mobility_type: MobilityType
    coordinates: AgentGeolocation
    static_signal: str = ""
    metadata: dict[str, Any] = {}


class MobilityAgent(Agent):
    def __init__(
        self,
        location: AgentGeolocation,
        mobility_type: MobilityType,
        static_signal: str,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.mobility = True
        self._metadata["geolocation"] = location.model_dump()
        self._metadata["mobility_type"] = mobility_type
        self._metadata["static_signal"] = static_signal
        self._proximity_agents: list[SearchResultAgent] = []
        self._checkedin_agents: dict[str, dict[str, Any]] = {}

        # @self.on_rest_post("/set_location", Location, Location)
        # async def _handle_location_update(_ctx: Context, req: Location):
        #     await self._update_geolocation(req)
        #     return self.location

        # @self.on_rest_get("/step", Location)
        # async def _handle_step(_ctx: Context):
        #     await self.step()
        #     return self.location

    @property
    def location(self) -> dict:
        return self.metadata["geolocation"] or {}

    @property
    def mobility_type(self) -> MobilityType:
        return self.metadata["mobility_type"]

    @property
    def static_signal(self) -> str:
        return self.metadata["static_signal"]

    @property
    def proximity_agents(self) -> list[SearchResultAgent]:
        # agents where this agent checked in
        return self._proximity_agents

    @property
    def checkedin_agents(self) -> dict[str, dict[str, Any]]:
        # agents that checked in with this agent
        return self._checkedin_agents

    def checkin_agent(self, addr: str, agent: CheckIn):
        self._checkedin_agents.update(
            {addr: {"timestamp": datetime.now(), "agent": agent}}
        )

    def checkout_agent(self, addr: str):
        del self._checkedin_agents[addr]

    def activate_agent(self, agent: SearchResultAgent):
        for activated in self._proximity_agents:
            if activated.address == agent.address:
                return

        self._proximity_agents.append(agent)

    def deactivate_agent(self, agent: SearchResultAgent):
        self._proximity_agents.remove(agent)

    async def _update_geolocation(self, location: Location):
        self._metadata["geolocation"]["latitude"] = location.latitude
        self._metadata["geolocation"]["longitude"] = location.longitude
        self._metadata["geolocation"]["radius"] = location.radius
        await self.invoke_location_update()

    async def step(self):
        self.location["latitude"] += 0.00003  # move 3 meter north
        self.location["latitude"] = round(self.location["latitude"], 6)
        self.location["longitude"] += 0.00003  # move 3 meter east
        self.location["longitude"] = round(self.location["longitude"], 6)
        await self.invoke_location_update()

    async def invoke_location_update(self):
        self._logger.info(
            f"Updating location {(self.location['latitude'], self.location['longitude'])}"
        )
        proximity_agents = geosearch_agents_by_proximity(
            self.location["latitude"],
            self.location["longitude"],
            self.location["radius"],
            30,
        )
        # send a check-in message to all agents that are in the current proximity
        for agent in proximity_agents:
            await self._send_checkin(agent)
        # find out which agents left proximity and send them a check-out message
        addresses_that_left_proximity = {a.address for a in self._proximity_agents} - {
            a.address for a in proximity_agents
        }
        agents_that_left_proximity = [
            a
            for a in self._proximity_agents
            if a.address in addresses_that_left_proximity
        ]
        for agent in agents_that_left_proximity:
            # send a check-out message to all agents that left the proximity
            await self._send_checkout(agent)
        self._proximity_agents = proximity_agents  # potential extra steps possible

    async def _send_checkin(self, agent: SearchResultAgent):
        ctx = self._build_context()
        # only send check-in to agents that are not already in the proximity list
        if agent in self._proximity_agents:
            return
        await ctx.send(
            agent.address,
            CheckIn(
                mobility_type=self.mobility_type,
                supported_protocols=list(self.protocols.keys()),
            ),
        )

    async def _send_checkout(self, agent: SearchResultAgent):
        ctx = self._build_context()
        # send checkout message to all agents that left the proximity
        await ctx.send(agent.address, CheckOut())
