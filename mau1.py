from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict
import pandas as pd
import os

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- BỘ NHỚ DỮ LIỆU ---
athlete_names: Dict[int, str] = {}
judge_scores: Dict[int, Dict[int, float]] = {} # {athlete_id: {judge_id: score}}
current_session = {"athlete_id": 101, "round_name": "Nội dung 1"}

class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws: WebSocket): await ws.accept(); self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket): self.active_connections.remove(ws)
    async def broadcast(self, data: dict):
        for conn in self.active_connections:
            try: await conn.send_json(data)
            except: pass

manager = ConnectionManager()

# --- CÁC API HỆ THỐNG ---
@app.post("/api/update-athlete-info")
async def update_athlete_info(data: dict):
    ath_id = data.get("athlete_id")
    name = data.get("name")
    round_name = data.get("round_name")
    
    if ath_id and name:
        athlete_names[ath_id] = name
        # Cập nhật tên nội dung và thông báo cho bảng xếp hạng reset
        current_session["round_name"] = round_name
        await manager.broadcast({"event": "session_update", "round_name": round_name})
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Thiếu thông tin")


@app.post("/api/set-active-athlete")
async def set_active_athlete(data: dict):
    ath_id = data.get("athlete_id")
    current_session["athlete_id"] = ath_id
    await manager.broadcast({"event": "change_athlete", "athlete_id": ath_id})
    return {"status": "success"}

@app.post("/api/submit-judge-score")
async def submit_judge_score(data: dict):
    ath_id = data.get("athlete_id")
    judge_id = data.get("judge_id")
    score = data.get("score_value")
    
    if ath_id not in judge_scores: judge_scores[ath_id] = {}
    judge_scores[ath_id][judge_id] = score
    
    await manager.broadcast({
        "event": "judge_score_received",
        "judge_id": judge_id,
        "score": score
    })
    return {"status": "ok"}

@app.post("/api/publish-score")
async def publish_score(data: dict):
    ath_id = data.get("athlete_id")
    if ath_id not in judge_scores: raise HTTPException(status_code=400, detail="Chưa có điểm")
    
    scores = list(judge_scores[ath_id].values())
    final_avg = sum(scores) / len(scores)
    
    await manager.broadcast({
        "event": "score_updated",
        "athlete_id": ath_id,
        "athlete_name": athlete_names.get(ath_id, f"VĐV #{ath_id}"),
        "all_scores": judge_scores[ath_id],
        "final_score": round(final_avg, 2)
    })
    return {"status": "published"}

@app.get("/api/export-excel/{round_name}")
async def export_excel(round_name: str):
    export_list = []
    for ath_id, scores in judge_scores.items():
        row = {
            "Athlete ID": ath_id,
            "Athlete Name": athlete_names.get(ath_id, "N/A"),
            **{f"GK{k}": v for k, v in scores.items()},
            "Final Score": round(sum(scores.values()) / len(scores), 2)
        }
        export_list.append(row)
    
    df = pd.DataFrame(export_list)
    filename = f"Ket_qua_{round_name}.xlsx"
    df.to_excel(filename, index=False)
    
    return FileResponse(filename, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename=filename)

# --- ROUTES HTML ---
@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f: return f.read()

@app.get("/referee", response_class=HTMLResponse)
async def read_referee():
    with open("referee.html", "r", encoding="utf-8") as f: return f.read()

@app.get("/judge", response_class=HTMLResponse)
async def read_judge():
    with open("Judge.html", "r", encoding="utf-8") as f: return f.read()

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(websocket)

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Gửi dữ liệu hiện tại ngay khi client kết nối thành công
    try:
        await websocket.send_json({
            "event": "session_update",
            "round_name": current_session["round_name"]
        })
        # Gửi dữ liệu điểm hiện có (nếu đã có)
        for ath_id, scores in judge_scores.items():
            await websocket.send_json({
                "event": "score_updated",
                "athlete_id": ath_id,
                "athlete_name": athlete_names.get(ath_id, f"VĐV #{ath_id}"),
                "all_scores": scores,
                "final_score": round(sum(scores.values()) / len(scores), 2) if scores else 0
            })
            
        while True: await websocket.receive_text()
    except WebSocketDisconnect: 
        manager.disconnect(websocket)
