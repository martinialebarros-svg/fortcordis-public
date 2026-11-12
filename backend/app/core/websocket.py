from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
from typing import List, Dict
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = []
        self.active_connections[client_id].append(websocket)
    
    def disconnect(self, websocket: WebSocket, client_id: str):
        if client_id in self.active_connections:
            self.active_connections[client_id].remove(websocket)
            if len(self.active_connections[client_id]) == 0:
                del self.active_connections[client_id]
    
    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)
    
    async def broadcast(self, message: str, client_id: str = None):
        """Envia mensagem para todos ou para um cliente específico"""
        if client_id and client_id in self.active_connections:
            for connection in self.active_connections[client_id]:
                await connection.send_text(message)
        else:
            # Broadcast para todos
            for connections in self.active_connections.values():
                for connection in connections:
                    await connection.send_text(message)
    
    async def notify_agenda_update(self, action: str, agendamento_id: int, data: dict = None):
        """Notifica todos os clientes sobre atualização na agenda"""
        message = {
            "type": "agenda_update",
            "action": action,  # created, updated, status_changed, cancelled, deleted
            "agendamento_id": agendamento_id,
            "data": data,
            "timestamp": str(datetime.now())
        }
        await self.broadcast(json.dumps(message))

manager = ConnectionManager()
