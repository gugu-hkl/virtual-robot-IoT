"use strict";

const ui = {
  selectionChip: document.getElementById("selection-chip"),
  selectedRobot: document.getElementById("selected-robot"),
  selectionText: document.getElementById("selection-text"),
  revisionLabel: document.getElementById("revision-label"),
  selectionWarning: document.getElementById("selection-warning"),
  notice: document.getElementById("notice"),
  mapTitle: document.getElementById("map-title"),
  mapStage: document.getElementById("map-stage"),
  canvas: document.getElementById("map-canvas"),
  fitButton: document.getElementById("fit-button"),
  liveBadge: document.getElementById("live-badge"),
  liveX: document.getElementById("live-x"),
  liveY: document.getElementById("live-y"),
  liveLinear: document.getElementById("live-linear"),
  liveAngular: document.getElementById("live-angular"),
  liveYaw: document.getElementById("live-yaw"),
  liveAge: document.getElementById("live-age"),
  moveForm: document.getElementById("move-form"),
  direction: document.getElementById("direction-input"),
  speed: document.getElementById("speed-input"),
  duration: document.getElementById("duration-input"),
  moveButton: document.getElementById("move-button"),
  moveLabel: document.querySelector("#move-button .button-label"),
  stopSelected: document.getElementById("stop-selected"),
  stopButtons: [...document.querySelectorAll(".robot-stop")],
  activityList: document.getElementById("activity-list"),
  activityEmpty: document.getElementById("activity-empty"),
  robots: {
    a: {
      card: document.getElementById("robot-a-card"),
      state: document.getElementById("robot-a-state"),
      summary: document.getElementById("robot-a-summary"),
    },
    b: {
      card: document.getElementById("robot-b-card"),
      state: document.getElementById("robot-b-state"),
      summary: document.getElementById("robot-b-summary"),
    },
  },
};

const canvasContext = ui.canvas.getContext("2d");
const app = {
  selectionKnown: false,
  selectionInitialized: false,
  selected: null,
  revision: null,
  selectionWarning: null,
  selectionError: "",
  commandError: "",
  selectionInFlight: false,
  movePending: false,
  stopPending: { a: false, b: false },
  robots: {
    a: { status: null, error: "", inFlight: false, trail: [], lastSimTime: null },
    b: { status: null, error: "", inFlight: false, trail: [], lastSimTime: null },
  },
  map: { width: 1, height: 1, centerX: 0, centerY: 0, scale: 3, fitted: false },
};

function formatNumber(value, digits = 1) {
  return Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function describeError(body, fallback) {
  const detail = body?.detail ?? body?.error;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  return fallback;
}

async function requestJSON(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { cache: "no-store", ...options });
  } catch {
    throw new Error("无法连接 Ubuntu FastAPI 服务");
  }
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error("服务端返回的数据不是 JSON");
  }
  if (!response.ok) {
    throw new Error(describeError(body, `HTTP ${response.status}`));
  }
  return body;
}

function addActivity(kind, text) {
  if (ui.activityEmpty.isConnected) ui.activityEmpty.remove();
  const item = document.createElement("li");
  item.dataset.kind = kind;
  item.textContent = `${new Date().toLocaleTimeString()} · ${text}`;
  ui.activityList.prepend(item);
  while (ui.activityList.children.length > 40) ui.activityList.lastElementChild.remove();
}

function renderNotice() {
  const selectedError = app.selectionKnown && app.selected && app.robots[app.selected].error
    ? `机器人 ${app.selected} 状态不可用：${app.robots[app.selected].error}` : "";
  const message = app.commandError || app.selectionError || app.selectionWarning || selectedError;
  ui.notice.hidden = !message;
  ui.notice.textContent = message;
}

function validSelection(value) {
  if (!value || ![null, "a", "b"].includes(value.selected_robot)
      || !Number.isInteger(value.selection_revision) || value.selection_revision < 0) {
    throw new Error("选择接口返回的数据格式无效");
  }
  return value;
}

function validStatus(value, robotId) {
  if (!value || value.robot_id !== robotId || value.position_source !== "odom"
      || !Number.isFinite(value.position_m?.x)
      || !Number.isFinite(value.position_m?.y)
      || !Number.isFinite(value.yaw_deg)
      || !Number.isFinite(value.linear_m_s)
      || !Number.isFinite(value.angular_rad_s)
      || !Number.isFinite(value.simulation_time_s)
      || !Number.isFinite(value.data_age_s)) {
    throw new Error(`机器人 ${robotId} 的里程计格式无效`);
  }
  return value;
}

function renderSelection() {
  if (!app.selectionKnown) {
    ui.selectionChip.dataset.state = "error";
    ui.selectionChip.textContent = "选择服务不可用";
    ui.selectedRobot.textContent = "?";
    ui.selectionText.textContent = "无法确认当前控制目标";
  } else if (app.selected === null) {
    ui.selectionChip.dataset.state = "waiting";
    ui.selectionChip.textContent = "等待刷脸";
    ui.selectedRobot.textContent = "—";
    ui.selectionText.textContent = "等待摄像头识别 A 或 B";
  } else {
    ui.selectionChip.dataset.state = "selected";
    ui.selectionChip.textContent = `已选机器人 ${app.selected}`;
    ui.selectedRobot.textContent = app.selected.toUpperCase();
    ui.selectionText.textContent = `网页控制目标：机器人 ${app.selected}`;
  }
  ui.revisionLabel.textContent = Number.isInteger(app.revision) ? `版本 ${app.revision}` : "版本 —";
  ui.selectionWarning.hidden = !app.selectionWarning;
  ui.selectionWarning.textContent = app.selectionWarning || "";
  ui.mapTitle.textContent = app.selectionKnown && app.selected
    ? `机器人 ${app.selected} · 里程计轨迹`
    : "等待刷脸选择";
  renderControlButtons();
  renderLiveStatus();
  for (const id of ["a", "b"]) renderRobotTile(id);
  drawMap();
}

async function refreshSelection() {
  if (app.selectionInFlight) return;
  app.selectionInFlight = true;
  try {
    const data = validSelection(await requestJSON("/display/selection"));
    const changed = !app.selectionInitialized || data.selection_revision !== app.revision
      || data.selected_robot !== app.selected;
    app.selectionKnown = true;
    app.selectionError = "";
    app.selectionWarning = typeof data.stop_warning === "string" ? data.stop_warning : null;
    app.selected = data.selected_robot;
    app.revision = data.selection_revision;
    if (changed) {
      if (app.selectionInitialized) {
        addActivity("event", app.selected
          ? `服务端选择了机器人 ${app.selected}` : "服务端清除了机器人选择");
      }
      app.selectionInitialized = true;
      app.map.fitted = false;
    }
    renderSelection();
  } catch (error) {
    if (!app.selectionError) addActivity("error", `无法读取机器人选择：${error.message}`);
    app.selectionError = `无法确认刷脸选择：${error.message}`;
    app.selectionKnown = false;
    renderSelection();
  } finally {
    app.selectionInFlight = false;
    renderNotice();
  }
}

function sampleTrail(robotId, status) {
  const record = app.robots[robotId];
  if (record.lastSimTime !== null && status.simulation_time_s < record.lastSimTime) {
    record.trail = []; // Webots 仿真重启，旧轨迹不再属于当前里程计坐标系。
  }
  record.lastSimTime = status.simulation_time_s;
  const point = { x: status.position_m.x * 100, y: status.position_m.y * 100 };
  const last = record.trail.at(-1);
  if (!last || Math.hypot(point.x - last.x, point.y - last.y) >= 0.5) {
    record.trail.push(point);
    if (record.trail.length > 500) record.trail.shift();
  }
}

function renderRobotTile(robotId) {
  const record = app.robots[robotId];
  const tile = ui.robots[robotId];
  if (!record.status) {
    tile.card.dataset.state = record.error ? "stale" : "waiting";
    tile.state.textContent = record.error ? "数据不可用" : "等待数据";
    tile.summary.textContent = "x — · y — · v —";
    return;
  }
  tile.card.dataset.state = app.selectionKnown && app.selected === robotId ? "selected" : "online";
  tile.state.textContent = app.selectionKnown && app.selected === robotId ? "当前选中" : "实时在线";
  tile.summary.textContent = `x ${formatNumber(record.status.position_m.x * 100)} · y ${formatNumber(record.status.position_m.y * 100)} · v ${formatNumber(record.status.linear_m_s * 100)} cm/s`;
}

function renderLiveStatus() {
  const status = app.selectionKnown && app.selected ? app.robots[app.selected].status : null;
  const ids = [ui.liveX, ui.liveY, ui.liveLinear, ui.liveAngular, ui.liveYaw, ui.liveAge];
  if (!status) {
    for (const element of ids) element.textContent = "—";
    ui.liveBadge.dataset.state = "waiting";
    ui.liveBadge.textContent = app.selected ? "数据不可用" : "等待选择";
    return;
  }
  ui.liveX.textContent = formatNumber(status.position_m.x * 100, 2);
  ui.liveY.textContent = formatNumber(status.position_m.y * 100, 2);
  ui.liveLinear.textContent = formatNumber(status.linear_m_s * 100, 2);
  ui.liveAngular.textContent = formatNumber(status.angular_rad_s, 3);
  ui.liveYaw.textContent = formatNumber(status.yaw_deg, 1);
  ui.liveAge.textContent = formatNumber(status.data_age_s, 2);
  ui.liveBadge.dataset.state = "stopped";
  ui.liveBadge.textContent = "实测在线";
}

async function refreshRobot(robotId) {
  const record = app.robots[robotId];
  if (record.inFlight) return;
  record.inFlight = true;
  try {
    const status = validStatus(await requestJSON(`/robots/${robotId}/status`), robotId);
    sampleTrail(robotId, status);
    record.status = status;
    record.error = "";
  } catch (error) {
    record.status = null;
    record.error = error.message;
  } finally {
    record.inFlight = false;
    renderRobotTile(robotId);
    if (app.selected === robotId) {
      renderLiveStatus();
      renderControlButtons();
      drawMap();
      renderNotice();
    }
  }
}

function renderControlButtons() {
  const ready = app.selectionKnown && app.selected !== null
    && app.robots[app.selected].status !== null;
  ui.moveButton.disabled = !ready || app.movePending;
  ui.moveLabel.textContent = !app.selectionKnown || app.selected === null
    ? "等待刷脸选择"
    : !ready ? "等待机器人状态" : `控制机器人 ${app.selected}`;
  ui.moveButton.classList.toggle("is-loading", app.movePending);
  ui.stopSelected.disabled = !app.selectionKnown || app.selected === null
    || app.stopPending[app.selected];
  ui.stopSelected.textContent = app.selected ? `停止机器人 ${app.selected}` : "停止当前机器人";
  for (const button of ui.stopButtons) {
    button.disabled = app.stopPending[button.dataset.robot];
  }
}

async function sendMove(event) {
  event.preventDefault();
  if (app.movePending) return;
  const robotId = app.selected;
  const revision = app.revision;
  const speed = Number(ui.speed.value);
  const duration = Number(ui.duration.value);
  const direction = ui.direction.value;
  if (!app.selectionKnown || !robotId || !app.robots[robotId].status) {
    app.commandError = "请先刷脸选择机器人，并等待其实时状态。";
    renderNotice();
    return;
  }
  if (!["forward", "backward", "left", "right"].includes(direction)
      || !Number.isFinite(speed) || speed <= 0 || speed > 20
      || !Number.isFinite(duration) || duration <= 0 || duration > 10) {
    app.commandError = "请填写有效的方向、轮缘速度和仿真时长。";
    renderNotice();
    return;
  }

  app.movePending = true;
  app.commandError = "";
  renderControlButtons();
  renderNotice();
  addActivity("command", `本页向机器人 ${robotId} 发送 ${direction}，${speed} cm/s，${duration} 仿真秒`);
  try {
    const response = await requestJSON(`/robots/${robotId}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction, speed, duration_s: duration, selection_revision: revision }),
    });
    if (response.accepted !== true || response.robot_id !== robotId
        || response.action !== "move" || response.selection_revision !== revision) {
      throw new Error("服务端没有返回匹配的控制确认");
    }
    addActivity("reply", `机器人 ${robotId} 的指令已被 ROS 网关接受；运动以后续 /odom 为准`);
    await refreshRobot(robotId);
  } catch (error) {
    app.commandError = `机器人 ${robotId} 的移动指令未确认：${error.message}`;
    addActivity("error", app.commandError);
  } finally {
    app.movePending = false;
    renderControlButtons();
    renderNotice();
    refreshSelection();
  }
}

async function stopRobot(robotId) {
  if (!['a', 'b'].includes(robotId) || app.stopPending[robotId]) return;
  app.stopPending[robotId] = true;
  app.commandError = "";
  renderControlButtons();
  renderNotice();
  addActivity("command", `本页请求停止机器人 ${robotId}`);
  try {
    const response = await requestJSON(`/robots/${robotId}/stop`, { method: "POST" });
    if (response.accepted !== true || response.robot_id !== robotId || response.action !== "stop") {
      throw new Error("服务端没有返回匹配的停止确认");
    }
    addActivity("reply", `ROS 网关已向机器人 ${robotId} 发送停止指令`);
    await refreshRobot(robotId);
  } catch (error) {
    app.commandError = `机器人 ${robotId} 的停止指令未确认：${error.message}`;
    addActivity("error", app.commandError);
  } finally {
    app.stopPending[robotId] = false;
    renderControlButtons();
    renderNotice();
  }
}

function selectedPoints() {
  if (!app.selectionKnown || !app.selected) return [];
  return app.robots[app.selected].trail;
}

function fitMap() {
  const points = [{ x: 0, y: 0 }, ...selectedPoints()];
  const status = app.selectionKnown && app.selected ? app.robots[app.selected].status : null;
  if (status) points.push({ x: status.position_m.x * 100, y: status.position_m.y * 100 });
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  app.map.centerX = (minX + maxX) / 2;
  app.map.centerY = (minY + maxY) / 2;
  app.map.scale = Math.max(0.01, Math.min(
    (app.map.width - 80) / Math.max(120, maxX - minX + 40),
    (app.map.height - 80) / Math.max(120, maxY - minY + 40)
  ));
  app.map.fitted = true;
  drawMap();
}

function screenPoint(x, y) {
  return {
    x: app.map.width / 2 + (x - app.map.centerX) * app.map.scale,
    y: app.map.height / 2 - (y - app.map.centerY) * app.map.scale,
  };
}

function drawMap() {
  if (!canvasContext) return;
  if (!app.map.fitted) {
    fitMap();
    return;
  }
  const ctx = canvasContext;
  const { width, height, centerX, centerY, scale } = app.map;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0a1928";
  ctx.fillRect(0, 0, width, height);
  const left = centerX - width / (2 * scale);
  const right = centerX + width / (2 * scale);
  const bottom = centerY - height / (2 * scale);
  const top = centerY + height / (2 * scale);
  ctx.font = '11px "Cascadia Code", Consolas, monospace';
  ctx.lineWidth = 1;
  for (let x = Math.ceil(left / 20) * 20, i = 0; x <= right && i < 400; x += 20, i += 1) {
    const sx = screenPoint(x, 0).x;
    ctx.strokeStyle = x === 0 ? "#668b9d" : "#243a4b";
    ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, height); ctx.stroke();
    if (20 * scale >= 38 && x !== 0) {
      ctx.fillStyle = "#91a8b5";
      ctx.fillText(String(x), sx + 3, height - 10);
    }
  }
  for (let y = Math.ceil(bottom / 20) * 20, i = 0; y <= top && i < 400; y += 20, i += 1) {
    const sy = screenPoint(0, y).y;
    ctx.strokeStyle = y === 0 ? "#668b9d" : "#243a4b";
    ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(width, sy); ctx.stroke();
    if (20 * scale >= 38 && y !== 0) {
      ctx.fillStyle = "#91a8b5";
      ctx.fillText(String(y), 9, sy - 4);
    }
  }
  const origin = screenPoint(0, 0);
  ctx.fillStyle = "#aecbd4";
  ctx.beginPath(); ctx.arc(origin.x, origin.y, 3, 0, Math.PI * 2); ctx.fill();
  ctx.fillText("O (0,0)", origin.x + 8, origin.y - 8);

  const points = selectedPoints();
  if (points.length > 1) {
    ctx.beginPath();
    points.forEach((point, index) => {
      const screen = screenPoint(point.x, point.y);
      if (index === 0) ctx.moveTo(screen.x, screen.y);
      else ctx.lineTo(screen.x, screen.y);
    });
    ctx.strokeStyle = "#58e2ec";
    ctx.lineWidth = 2.5;
    ctx.stroke();
  }
  const status = app.selectionKnown && app.selected ? app.robots[app.selected].status : null;
  if (!status) return;
  const position = screenPoint(status.position_m.x * 100, status.position_m.y * 100);
  if (position.x < 28 || position.x > width - 28 || position.y < 28 || position.y > height - 28) {
    app.map.fitted = false;
    fitMap();
    return;
  }
  ctx.save();
  ctx.translate(position.x, position.y);
  ctx.rotate(-status.yaw_deg * Math.PI / 180);
  ctx.fillStyle = "#58e2ec";
  ctx.beginPath(); ctx.arc(0, 0, 10, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#08202a";
  ctx.beginPath(); ctx.moveTo(10, 0); ctx.lineTo(-5, -5); ctx.lineTo(-5, 5); ctx.closePath(); ctx.fill();
  ctx.restore();
  ctx.fillStyle = "#d9ffff";
  ctx.fillText(app.selected.toUpperCase(), position.x + 14, position.y - 12);
}

function resizeMap() {
  if (!canvasContext) return;
  const bounds = ui.mapStage.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  app.map.width = Math.max(1, Math.round(bounds.width));
  app.map.height = Math.max(1, Math.round(bounds.height));
  ui.canvas.width = Math.round(app.map.width * ratio);
  ui.canvas.height = Math.round(app.map.height * ratio);
  canvasContext.setTransform(ratio, 0, 0, ratio, 0, 0);
  app.map.fitted = false;
  drawMap();
}

ui.moveForm.addEventListener("submit", sendMove);
ui.stopSelected.addEventListener("click", () => {
  if (app.selectionKnown && app.selected) stopRobot(app.selected);
});
for (const button of ui.stopButtons) {
  button.addEventListener("click", () => stopRobot(button.dataset.robot));
}
ui.fitButton.addEventListener("click", fitMap);

if (canvasContext) {
  new ResizeObserver(resizeMap).observe(ui.mapStage);
  resizeMap();
} else {
  app.selectionError = "当前浏览器不支持 Canvas，无法绘制坐标图。";
  renderNotice();
}
renderSelection();
refreshSelection();
refreshRobot("a");
refreshRobot("b");
setInterval(() => {
  refreshSelection();
  refreshRobot("a");
  refreshRobot("b");
}, 500);
