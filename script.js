// Vehicle Logs Dashboard Script

let allLogs = [];
let hourChart = null;
let dashboardDate = "";

async function loadData() {
  const msgEl = document.getElementById("message");
  try {
    console.log("[DASHBOARD] Loading vehicle records...");
    allLogs = await getVehicleLogs();
    dashboardDate = getDashboardDate();
    document.getElementById("dashboardDate").innerText = dashboardDate;

    showSummary();
    showChart();
    showTable(allLogs);
    msgEl.innerText = "";
  } catch (error) {
    const errorDetails = error?.message || error;
    console.error("[DASHBOARD ERROR] Failed to load data:", error);
    msgEl.innerText = `Error: ${errorDetails}`;
  }
}

function getLocalDateString(d = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function getDashboardDate() {
  const localToday = getLocalDateString();
  const foundToday = allLogs.some((log) => log.entryTime?.substring(0, 10) === localToday);
  if (foundToday) return localToday;

  return allLogs.length > 0 ? allLogs[allLogs.length - 1].entryTime.substring(0, 10) : localToday;
}

function getTodayLogs() {
  return allLogs.filter((log) => log.entryTime?.substring(0, 10) === dashboardDate);
}

function getStayMinutes(log) {
  if (!log.exitTime) return null;
  const diffMs = new Date(log.exitTime.replace(" ", "T")) - new Date(log.entryTime.replace(" ", "T"));
  return Math.max(0, Math.round(diffMs / 60000));
}

function formatDuration(minutes) {
  if (minutes === null || isNaN(minutes)) return "-";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m}m`;
}

function showSummary() {
  const todayLogs = getTodayLogs();
  
  // Currently inside: all vehicles currently on premise
  const insideNow = allLogs.filter((log) => log.status === "Inside").length;

  let exitedToday = 0;
  let totalMinutes = 0;

  todayLogs.forEach((log) => {
    if (log.status === "Exited" || log.exitTime) {
      exitedToday++;
      totalMinutes += getStayMinutes(log) || 0;
    }
  });

  document.getElementById("totalToday").innerText = todayLogs.length;
  document.getElementById("insideNow").innerText = insideNow;
  document.getElementById("exitedToday").innerText = exitedToday;
  document.getElementById("avgStay").innerText = exitedToday > 0 ? formatDuration(Math.round(totalMinutes / exitedToday)) : "-";
}

function showTable(list) {
  const tbody = document.getElementById("logTableBody");
  if (!list.length) {
    tbody.innerHTML = "<tr><td colspan='7'>No records found</td></tr>";
    return;
  }

  tbody.innerHTML = list.map((log, i) => {
    const exitText = log.exitTime || "-";
    const durationText = log.exitTime ? formatDuration(getStayMinutes(log)) : "-";
    const statusClass = log.status === "Inside" ? "inside" : "";
    const imageLink = log.imageUrl
      ? `<a href="${log.imageUrl}" target="_blank" class="plate-link" style="color: #2f6fb0; text-decoration: underline; font-weight: bold;">View Photo</a>`
      : "-";

    return `
      <tr>
        <td>${i + 1}</td>
        <td><strong>${log.plate}</strong></td>
        <td>${log.entryTime}</td>
        <td>${exitText}</td>
        <td>${durationText}</td>
        <td class="${statusClass}">${log.status}</td>
        <td>${imageLink}</td>
      </tr>
    `;
  }).join("");
}

function filterTable() {
  const search = document.getElementById("searchBox").value.trim().toUpperCase();
  const status = document.getElementById("statusFilter").value;

  const filtered = allLogs.filter((log) => {
    const plateMatch = log.plate.toUpperCase().includes(search);
    const statusMatch = status === "All" || log.status === status;
    return plateMatch && statusMatch;
  });

  showTable(filtered);
}

function showChart() {
  const labels = [];
  const counts = Array(24).fill(0);

  // Cover all 24 hours (00:00 to 23:00) so evening/night entries are not dropped
  for (let h = 0; h < 24; h++) {
    labels.push(`${String(h).padStart(2, "0")}:00`);
  }

  getTodayLogs().forEach((log) => {
    if (!log.entryTime) return;
    // log.entryTime format: "YYYY-MM-DD HH:mm:ss"
    const timePart = log.entryTime.split(" ")[1];
    if (timePart) {
      const hour = parseInt(timePart.split(":")[0], 10);
      if (hour >= 0 && hour < 24) {
        counts[hour]++;
      }
    }
  });

  const ctx = document.getElementById("hourChart");
  if (hourChart) hourChart.destroy();

  hourChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [{
        label: "Vehicles entered",
        data: counts,
        backgroundColor: "#2f6fb0",
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }
    }
  });
}

function showPage(name) {
  ["dashboard", "logs", "about"].forEach((p) => {
    document.getElementById(`page-${p}`).classList.toggle("hidden", p !== name);
    document.getElementById(`link-${p}`).classList.toggle("active", p === name);
  });
}

// Handles upload for the 4 options:
// gate: "entry" | "exit"
// mediaType: "photo" | "video"
async function handleUpload(gate, mediaType) {
  const inputId = `${gate}${mediaType === "photo" ? "Photo" : "Video"}Input`;
  const btnId = `${gate}${mediaType === "photo" ? "Photo" : "Video"}Btn`;
  const msgId = `${gate}Msg`;

  const input = document.getElementById(inputId);
  const button = document.getElementById(btnId);
  const msg = document.getElementById(msgId);

  if (!input.files || input.files.length === 0) {
    const warn = `Please choose a ${mediaType} file before clicking upload.`;
    console.warn(`[UPLOAD VALIDATION] ${warn}`);
    msg.innerText = warn;
    return;
  }

  const selectedFile = input.files[0];
  console.log(`[UPLOAD START] User triggered ${gate} ${mediaType} with file '${selectedFile.name}' (${(selectedFile.size / 1024).toFixed(1)} KB)`);

  button.disabled = true;
  msg.innerText = `Uploading and running ANPR on ${mediaType}...`;

  try {
    const endpoint = `/api/${gate}/${mediaType}`;
    const result = await uploadGateMedia(endpoint, selectedFile);

    console.log(`[UPLOAD COMPLETE] Result:`, result);
    msg.innerText = result.message || "Processed successfully!";
    input.value = "";
    await loadData();
  } catch (error) {
    console.error(`[UPLOAD ERROR] Failed ${gate} ${mediaType} upload:`, error);
    msg.innerText = `Upload failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

// Initial load
loadData();
