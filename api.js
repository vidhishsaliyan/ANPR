// Pure API Client - All requests go to the FastAPI Backend

const API_URL = "http://localhost:8001";

function formatTime(val) {
  if (!val) return "-";
  const d = new Date(val);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// Fetches logs from FastAPI backend (which talks to Supabase)
async function getVehicleLogs() {
  const res = await fetch(`${API_URL}/api/logs`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to load logs from server");
  }

  const data = await res.json();
  return data.map((row) => ({
    id: row.id,
    plate: row.plate,
    entryTime: formatTime(row.entry_time),
    exitTime: row.exit_time ? formatTime(row.exit_time) : null,
    status: row.status,
    imageUrl: row.image_url,
  }));
}

// Sends file to one of the 4 endpoints
async function uploadGateMedia(endpointPath, file) {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_URL}${endpointPath}`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Upload failed");
  }

  return res.json();
}
