"use strict";

const ui = {
  canvas: document.getElementById("map-canvas"),
  mapStage: document.getElementById("map-stage"),
  fitButton: document.getElementById("fit-button"),

  connectionChip: document.getElementById("connection-chip"),
  connectionText: document.getElementById("connection-text"),
  notice: document.getElementById("notice"),
  staleHint: document.getElementById("stale-hint"),

  motionBadge: document.getElementById("motion-badge"),
  positionX: document.getElementById("position-x"),
  positionY: document.getElementById("position-y"),
  onlineValue: document.getElementById("online-value"),
  motionValue: document.getElementById("motion-value"),
  directionValue: document.getElementById("direction-value"),
  speedValue: document.getElementById("speed-value"),
  taskValue: document.getElementById("task-value"),

  moveForm: document.getElementById("move-form"),
  moveButton: document.getElementById("move-button"),
  directionInput: document.getElementById("direction-input"),
  speedInput: document.getElementById("speed-input"),
  durationInput: document.getElementById("duration-input"),
  taskButtons: [...document.querySelectorAll(".task-button")],
  stopButton: document.getElementById("stop-button"),

  sensorButton: document.getElementById("sensor-button"),
  sensorDistance: document.getElementById("sensor-distance"),
  sensorTemperature: document.getElementById("sensor-temperature"),
  sensorNote: document.getElementById("sensor-note"),

  activityList: document.getElementById("activity-list"),
  activityEmpty: document.getElementById("activity-empty"),
};

const ctx = ui.canvas.getContext("2d");

const state = {
  status: null,
  displayedPosition: null,
  animationFrame: null,

  view: {
    centerX: 0,
    centerY: 0,
    scale: 4,
  },
  viewFitted: false,
  width: 1,
  height: 1,

  statusInFlight: false,
  sensorInFlight: false,
  pendingCommands: 0,
  stopPending: false,
  statusGeneration: 0,
  latestCommandId: 0,
  seenTrajectoryCount: 0,

  connectionError: "",
  controlError: "",
};

const directionNames = {
  forward: "前进 · Y+",
  backward: "后退 · Y−",
  left: "向左 · X−",
  right: "向右 · X+",
};

const reducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)"
);

function numberText(value) {
  return Number.isFinite(value) ? value.toFixed(3) : "—";
}

function pointText(point) {
  return `(${numberText(point.x)}, ${numberText(point.y)}) cm`;
}

function showNotice() {
  const message = state.controlError || state.connectionError;
  ui.notice.hidden = !message;
  ui.notice.textContent = message;
}

function setConnection(connected) {
  ui.connectionChip.dataset.state = connected ? "online" : "offline";
  ui.connectionText.textContent = connected ? "已连接" : "连接失败";
  ui.staleHint.hidden = connected || state.status === null;

  if (!connected) {
    ui.onlineValue.textContent = "无法确认";
  } else if (state.status) {
    ui.onlineValue.textContent = state.status.online ? "在线" : "离线";
  }
}

function addActivity(kind, text) {
  if (ui.activityEmpty.isConnected) {
    ui.activityEmpty.remove();
  }

  const item = document.createElement("li");
  item.dataset.kind = kind;
  item.textContent = text;
  ui.activityList.prepend(item);

  while (ui.activityList.children.length > 40) {
    ui.activityList.lastElementChild.remove();
  }
}

function serverEventText(point) {
  const event = point.event;

  if (event === "progress") {
    return null; // 位置变化由图和数字展示，避免记录列表被轮询刷满
  }

  const names = {
    start: "轨迹起点",
    move: "移动起点",
    stop: "停止",
    segment_end: "路段终点",
    "task:forward": "forward 任务起点",
    "task:square": "square 任务起点",
  };

  if (!Object.hasOwn(names, event)) {
    return null;
  }

  return `服务端事件 · ${names[event]} ${pointText(point)}`;
}

function recordServerEvents(trajectory) {
  if (trajectory.length < state.seenTrajectoryCount) {
    state.seenTrajectoryCount = 0;
  }

  // 初次打开页面时，只显示最近一部分真实轨迹事件。
  const firstIndex =
    state.seenTrajectoryCount === 0
      ? Math.max(0, trajectory.length - 80)
      : state.seenTrajectoryCount;

  for (let index = firstIndex; index < trajectory.length; index += 1) {
    const point = trajectory[index];
    if (!point || typeof point.event !== "string") {
      continue;
    }

    const text = serverEventText(point);
    if (text) {
      addActivity("event", text);
    }
  }

  state.seenTrajectoryCount = trajectory.length;
}

function validateStatus(value) {
  if (
    !value ||
    !value.position ||
    !Number.isFinite(value.position.x) ||
    !Number.isFinite(value.position.y) ||
    !Array.isArray(value.trajectory)
  ) {
    throw new Error("服务端状态缺少有效的 position 或 trajectory");
  }

  return value;
}

function updateStatusText(status) {
  ui.positionX.textContent = numberText(status.position.x);
  ui.positionY.textContent = numberText(status.position.y);

  ui.onlineValue.textContent = status.online ? "在线" : "离线";
  ui.motionValue.textContent = status.moving ? "运动中" : "已停止";
  ui.directionValue.textContent =
    directionNames[status.direction] || "—";
  ui.speedValue.textContent = Number.isFinite(status.speed)
    ? status.speed.toFixed(1)
    : "—";
  ui.taskValue.textContent = status.current_task || "—";

  ui.motionBadge.dataset.state = status.moving ? "moving" : "stopped";
  ui.motionBadge.textContent = status.moving ? "运动中" : "已停止";
}

function validTrajectory() {
  if (!state.status) {
    return [];
  }

  return state.status.trajectory.filter(
    (point) =>
      point &&
      Number.isFinite(point.x) &&
      Number.isFinite(point.y)
  );
}

function worldToScreen(x, y) {
  return {
    x: state.width / 2 + (x - state.view.centerX) * state.view.scale,
    // Canvas 的 y 向下，因此这里必须取反。
    y: state.height / 2 - (y - state.view.centerY) * state.view.scale,
  };
}

function fitToTrajectory() {
  const points = validTrajectory();
  const xs = [0];
  const ys = [0];

  for (const point of points) {
    xs.push(point.x);
    ys.push(point.y);
  }

  if (state.status) {
    xs.push(state.status.position.x);
    ys.push(state.status.position.y);
  }

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  state.view.centerX = (minX + maxX) / 2;
  state.view.centerY = (minY + maxY) / 2;

  // 至少给初始原点留出约 120 cm 的视野，并在轨迹四周留白。
  const spanX = Math.max(120, maxX - minX + 40);
  const spanY = Math.max(120, maxY - minY + 40);

  state.view.scale = Math.max(
    0.001,
    Math.min(
      (state.width - 80) / spanX,
      (state.height - 80) / spanY
    )
  );

  state.viewFitted = true;
  drawMap();
}

function keepRobotVisible(position) {
  if (!state.viewFitted) {
    fitToTrajectory();
    return;
  }

  const screen = worldToScreen(position.x, position.y);
  const margin = 38;

  if (
    screen.x < margin ||
    screen.x > state.width - margin ||
    screen.y < margin ||
    screen.y > state.height - margin
  ) {
    fitToTrajectory();
  }
}

function drawGrid() {
  const { width, height } = state;
  const { centerX, centerY, scale } = state.view;
  const left = centerX - width / (2 * scale);
  const right = centerX + width / (2 * scale);
  const bottom = centerY - height / (2 * scale);
  const top = centerY + height / (2 * scale);

  const step = 20;
  const labelTicks = step * scale >= 38;

  ctx.save();
  ctx.font = '11px "Cascadia Code", Consolas, monospace';
  ctx.lineWidth = 1;

  let count = 0;
  for (
    let x = Math.ceil(left / step) * step;
    x <= right && count < 600;
    x += step, count += 1
  ) {
    const sx = worldToScreen(x, 0).x;
    ctx.strokeStyle = x === 0 ? "#6d98a8" : "#27394a";
    ctx.beginPath();
    ctx.moveTo(sx + 0.5, 0);
    ctx.lineTo(sx + 0.5, height);
    ctx.stroke();

    if (labelTicks && x !== 0) {
      ctx.fillStyle = "#8ca8b6";
      ctx.fillText(String(x), sx + 4, height - 12);
    }
  }

  count = 0;
  for (
    let y = Math.ceil(bottom / step) * step;
    y <= top && count < 600;
    y += step, count += 1
  ) {
    const sy = worldToScreen(0, y).y;
    ctx.strokeStyle = y === 0 ? "#6d98a8" : "#27394a";
    ctx.beginPath();
    ctx.moveTo(0, sy + 0.5);
    ctx.lineTo(width, sy + 0.5);
    ctx.stroke();

    if (labelTicks && y !== 0) {
      ctx.fillStyle = "#8ca8b6";
      ctx.fillText(String(y), 10, sy - 5);
    }
  }

  const origin = worldToScreen(0, 0);
  if (
    origin.x >= 0 &&
    origin.x <= width &&
    origin.y >= 0 &&
    origin.y <= height
  ) {
    ctx.fillStyle = "#a9c8d2";
    ctx.beginPath();
    ctx.arc(origin.x, origin.y, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillText("O (0, 0)", origin.x + 9, origin.y - 9);
  }

  ctx.restore();
}

function drawTrajectory(points) {
  if (points.length < 2) {
    return;
  }

  ctx.save();
  ctx.beginPath();

  points.forEach((point, index) => {
    const screen = worldToScreen(point.x, point.y);
    if (index === 0) {
      ctx.moveTo(screen.x, screen.y);
    } else {
      ctx.lineTo(screen.x, screen.y);
    }
  });

  ctx.strokeStyle = "#58e2ec";
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.shadowColor = "rgba(88, 226, 236, 0.35)";
  ctx.shadowBlur = 8;
  ctx.stroke();
  ctx.restore();
}

function drawEventMarkers(points) {
  ctx.save();
  ctx.font = '10px "Cascadia Code", Consolas, monospace';

  for (const point of points) {
    const event = point.event;
    if (event === "progress") {
      continue;
    }

    const screen = worldToScreen(point.x, point.y);
    if (
      screen.x < -30 ||
      screen.x > state.width + 30 ||
      screen.y < -30 ||
      screen.y > state.height + 30
    ) {
      continue;
    }

    if (event === "segment_end") {
      ctx.fillStyle = "#b8f4f4";
      ctx.fillRect(screen.x - 3, screen.y - 3, 6, 6);
      continue;
    }

    if (event === "stop") {
      ctx.strokeStyle = "#ff7881";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(screen.x - 6, screen.y - 6);
      ctx.lineTo(screen.x + 6, screen.y + 6);
      ctx.moveTo(screen.x + 6, screen.y - 6);
      ctx.lineTo(screen.x - 6, screen.y + 6);
      ctx.stroke();
      ctx.fillStyle = "#ffb5ba";
      ctx.fillText("STOP", screen.x + 9, screen.y - 9);
      continue;
    }

    if (event === "move" || event.startsWith("task:")) {
      ctx.strokeStyle = "#d7ffff";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, 5, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = "#d7ffff";
      ctx.fillText(
        event === "move" ? "MOVE" : event.toUpperCase(),
        screen.x + 9,
        screen.y - 9
      );
    }
  }

  ctx.restore();
}

function drawRobot() {
  if (!state.status) {
    return;
  }

  const position = state.displayedPosition || state.status.position;
  const screen = worldToScreen(position.x, position.y);

  ctx.save();
  ctx.translate(screen.x, screen.y);
  ctx.shadowColor = "rgba(88, 226, 236, 0.6)";
  ctx.shadowBlur = 18;

  ctx.fillStyle = "#58e2ec";
  ctx.beginPath();
  ctx.arc(0, 0, 10, 0, Math.PI * 2);
  ctx.fill();

  ctx.shadowBlur = 0;
  ctx.strokeStyle = "#eaffff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(0, 0, 10, 0, Math.PI * 2);
  ctx.stroke();

  const angles = {
    forward: -Math.PI / 2,
    backward: Math.PI / 2,
    left: Math.PI,
    right: 0,
  };

  if (
    state.status.moving &&
    Object.hasOwn(angles, state.status.direction)
  ) {
    ctx.rotate(angles[state.status.direction]);
    ctx.fillStyle = "#09212a";
    ctx.beginPath();
    ctx.moveTo(6, 0);
    ctx.lineTo(-4, -4);
    ctx.lineTo(-4, 4);
    ctx.closePath();
    ctx.fill();
  } else {
    ctx.fillStyle = "#09212a";
    ctx.beginPath();
    ctx.arc(0, 0, 3, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}

function drawMap() {
  if (!ctx) {
    return;
  }

  ctx.clearRect(0, 0, state.width, state.height);
  drawGrid();

  const points = validTrajectory();
  drawTrajectory(points);
  drawEventMarkers(points);
  drawRobot();
}

function animateRobotTo(position, snap = false) {
  if (state.animationFrame !== null) {
    cancelAnimationFrame(state.animationFrame);
    state.animationFrame = null;
  }

  const target = { x: position.x, y: position.y };

  if (!state.displayedPosition || snap || reducedMotion.matches) {
    state.displayedPosition = target;
    drawMap();
    return;
  }

  const from = { ...state.displayedPosition };
  const startedAt = performance.now();
  const animationMs = 350;

  function frame(now) {
    const progress = Math.min(1, (now - startedAt) / animationMs);
    const eased = 1 - Math.pow(1 - progress, 3);

    state.displayedPosition = {
      x: from.x + (target.x - from.x) * eased,
      y: from.y + (target.y - from.y) * eased,
    };

    drawMap();

    if (progress < 1) {
      state.animationFrame = requestAnimationFrame(frame);
    } else {
      // 动画结束时采用服务端坐标，不累计前端误差。
      state.displayedPosition = target;
      state.animationFrame = null;
      drawMap();
    }
  }

  state.animationFrame = requestAnimationFrame(frame);
}

function applyStatus(rawStatus, { snap = false } = {}) {
  const status = validateStatus(rawStatus);
  state.status = status;

  updateStatusText(status);
  recordServerEvents(status.trajectory);
  keepRobotVisible(status.position);
  animateRobotTo(status.position, snap);
}

function resizeCanvas() {
  if (!ctx) {
    return;
  }

  const rect = ui.mapStage.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);

  state.width = Math.max(1, Math.round(rect.width));
  state.height = Math.max(1, Math.round(rect.height));

  ui.canvas.width = Math.round(state.width * ratio);
  ui.canvas.height = Math.round(state.height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

  fitToTrajectory();
}

function httpError(response, payload) {
  let detail = "";

  if (payload && typeof payload === "object") {
    if (typeof payload.detail === "string") {
      detail = payload.detail;
    } else if (Array.isArray(payload.detail)) {
      detail = payload.detail
        .map((item) => item.msg || "参数无效")
        .join("；");
    }
  } else if (typeof payload === "string") {
    detail = payload.slice(0, 120);
  }

  return `HTTP ${response.status}${detail ? `：${detail}` : ""}`;
}

async function requestJSON(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);

  try {
    const response = await fetch(path, {
      cache: "no-store",
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
      signal: controller.signal,
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      throw new Error(httpError(response, payload));
    }

    if (typeof payload !== "object" || payload === null) {
      throw new Error("服务端没有返回预期的 JSON");
    }

    return payload;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("请求超时，未收到服务端确认");
    }

    if (error instanceof TypeError) {
      throw new Error("无法连接 Ubuntu 服务端");
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function refreshStatus() {
  // 上一次查询未完成，或控制请求未结束时，不再发起新查询。
  if (state.statusInFlight || state.pendingCommands > 0) {
    return;
  }

  state.statusInFlight = true;
  const generation = state.statusGeneration;

  try {
    const status = await requestJSON("/status");

    // 控制指令发出后，丢弃比该指令更早开始的查询结果。
    if (generation !== state.statusGeneration) {
      return;
    }

    applyStatus(status);
    state.connectionError = "";
    setConnection(true);
    showNotice();
  } catch (error) {
    if (generation !== state.statusGeneration) {
      return;
    }

    state.connectionError = `状态查询失败：${error.message}`;
    setConnection(false);
    showNotice();
  } finally {
    state.statusInFlight = false;
  }
}

async function refreshSensor() {
  if (state.sensorInFlight) {
    return;
  }

  state.sensorInFlight = true;
  ui.sensorButton.disabled = true;

  try {
    const sensor = await requestJSON("/sensor");

    if (
      !Number.isFinite(sensor.distance) ||
      !Number.isFinite(sensor.temperature)
    ) {
      throw new Error("服务端传感器数据格式不正确");
    }

    ui.sensorDistance.textContent = String(sensor.distance);
    ui.sensorTemperature.textContent = String(sensor.temperature);
    ui.sensorNote.textContent =
      "模拟读数；当前后端返回固定值，未定义读数单位。";
  } catch (error) {
    ui.sensorDistance.textContent = "—";
    ui.sensorTemperature.textContent = "—";
    ui.sensorNote.textContent =
      `模拟读数获取失败：${error.message}`;
  } finally {
    state.sensorInFlight = false;
    ui.sensorButton.disabled = false;
  }
}

function setButtonLoading(button, loading) {
  button.classList.toggle("is-loading", loading);
  button.setAttribute("aria-busy", String(loading));
}

function updateControlButtons() {
  const normalCommandBusy = state.pendingCommands > 0;

  ui.moveButton.disabled = normalCommandBusy;
  for (const button of ui.taskButtons) {
    button.disabled = normalCommandBusy;
  }

  // 移动或任务请求等待响应时，停止按钮仍可点击。
  ui.stopButton.disabled = state.stopPending;
}

async function sendCommand(path, body, button, label, snap = false) {
  const commandId = ++state.latestCommandId;
  state.statusGeneration += 1;
  state.pendingCommands += 1;

  if (snap) {
    state.stopPending = true;
  }

  setButtonLoading(button, true);
  updateControlButtons();

  try {
    const pending = requestJSON(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    addActivity("command", `本页指令 · ${label}`);
    const response = await pending;

    if (!response.status) {
      throw new Error("控制接口没有返回 status，无法确认机器人位置");
    }

    if (typeof response.message === "string") {
      addActivity("reply", `服务端响应 · ${response.message}`);
    }

    // 若在等待期间又按了停止，旧指令响应不能覆盖更新的停止位置。
    if (commandId === state.latestCommandId) {
      applyStatus(response.status, { snap });
      state.controlError = "";
      state.connectionError = "";
      setConnection(true);
      showNotice();
    }
  } catch (error) {
    addActivity("error", `指令未确认 · ${label} · ${error.message}`);

    if (commandId === state.latestCommandId) {
      state.controlError =
        `${label} 未收到成功确认：${error.message}。请查看当前状态。`;
      showNotice();
    }
  } finally {
    state.pendingCommands -= 1;

    if (snap) {
      state.stopPending = false;
    }

    setButtonLoading(button, false);
    updateControlButtons();

    if (state.pendingCommands === 0) {
      refreshStatus();
    }
  }
}

ui.moveForm.addEventListener("submit", (event) => {
  event.preventDefault();

  const direction = ui.directionInput.value;
  const speed = Number(ui.speedInput.value);
  const duration_s = Number(ui.durationInput.value);

  if (
    !Object.hasOwn(directionNames, direction) ||
    !Number.isFinite(speed) ||
    !Number.isFinite(duration_s) ||
    speed <= 0 ||
    speed > 100 ||
    duration_s <= 0 ||
    duration_s > 60
  ) {
    state.controlError = "请填写有效的方向、速度和时长。";
    showNotice();
    return;
  }

  sendCommand(
    "/move",
    { direction, speed, duration_s },
    ui.moveButton,
    `移动 ${direction}，${speed} cm/s，${duration_s} 秒`
  );
});

for (const button of ui.taskButtons) {
  button.addEventListener("click", () => {
    const name = button.dataset.task;

    sendCommand(
      "/task",
      { name },
      button,
      `执行任务 ${name}`
    );
  });
}

ui.stopButton.addEventListener("click", () => {
  sendCommand(
    "/stop",
    null,
    ui.stopButton,
    "停止",
    true
  );
});

ui.fitButton.addEventListener("click", fitToTrajectory);
ui.sensorButton.addEventListener("click", refreshSensor);

if (!ctx) {
  state.connectionError = "当前浏览器不支持 Canvas，无法绘制坐标图。";
  showNotice();
} else {
  const observer = new ResizeObserver(resizeCanvas);
  observer.observe(ui.mapStage);
  resizeCanvas();
}

refreshStatus();
refreshSensor();
setInterval(refreshStatus, 500);