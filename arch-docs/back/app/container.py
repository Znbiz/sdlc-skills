from that_depends import BaseContainer, providers

from app.settings import GatewaySettings


class AppContainer(BaseContainer):
    settings: providers.Singleton[GatewaySettings] = providers.Singleton(GatewaySettings)
