"""Server UI assets for per-device geofence configuration."""
from __future__ import annotations

import html
import json


def wifi_ssid_datalist_html(suggestions, list_id="wifi-ssid-suggestions"):
    options = "".join(f'<option value="{html.escape(s)}"></option>' for s in suggestions if s)
    return f'<datalist id="{list_id}">{options}</datalist>'


def geofence_leaflet_head():
    return """
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
    <style>
      #geofence-zone-map { height: 360px; border-radius: 10px; }
      .geofence-zone-row { border: 1px solid #e2e8f0; border-radius: 10px; padding: 1rem; margin-bottom: 0.75rem; }
      .wifi-network-row { border: 1px solid #e2e8f0; border-radius: 10px; padding: 0.85rem; margin-bottom: 0.75rem; }
      #geofence-map-modal .modal-dialog { max-width: 920px; }
    </style>
    """


def geofence_page_scripts(config, device, suggestions):
    config_json = json.dumps(config)
    suggestions_json = json.dumps(suggestions)
    default_lat = device.get("lastLatitude")
    default_lng = device.get("lastLongitude")
    if default_lat is None or default_lng is None:
        default_lat, default_lng = 28.6139, 77.2090
    return f"""
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
    (function() {{
      const initialConfig = {config_json};
      const wifiSuggestions = {suggestions_json};
      const defaultCenter = [{float(default_lat)}, {float(default_lng)}];
      const datalistId = "wifi-ssid-suggestions";

      let modalMap = null;
      let modalMarker = null;
      let modalCircle = null;
      let editingZoneIndex = null;

      function uid() {{
        return "zone_" + Math.random().toString(36).slice(2, 10);
      }}

      function wifiRowHtml(entry, index) {{
        const ssid = entry.ssid || "";
        const connect = entry.alertOnConnect !== false ? "checked" : "";
        const disconnect = entry.alertOnDisconnect !== false ? "checked" : "";
        return `
          <div class="wifi-network-row" data-index="${{index}}">
            <div class="row g-2 align-items-end">
              <div class="col-md-5">
                <label class="form-label small fw-bold">Wi-Fi SSID</label>
                <input class="form-control wifi-ssid-input" list="${{datalistId}}" value="${{escapeAttr(ssid)}}" placeholder="Office-LAN">
              </div>
              <div class="col-md-3">
                <div class="form-check">
                  <input class="form-check-input wifi-alert-connect" type="checkbox" ${{connect}}>
                  <label class="form-check-label small">Email on connect</label>
                </div>
              </div>
              <div class="col-md-3">
                <div class="form-check">
                  <input class="form-check-input wifi-alert-disconnect" type="checkbox" ${{disconnect}}>
                  <label class="form-check-label small">Email on disconnect</label>
                </div>
              </div>
              <div class="col-md-1 text-end">
                <button type="button" class="btn btn-outline-danger btn-sm wifi-remove-btn" title="Remove">×</button>
              </div>
            </div>
          </div>`;
      }}

      function zoneRowHtml(zone, index) {{
        const label = zone.label || ("Zone " + (index + 1));
        const lat = zone.latitude != null ? zone.latitude : defaultCenter[0];
        const lng = zone.longitude != null ? zone.longitude : defaultCenter[1];
        const radius = zone.radiusMeters || 200;
        const enter = zone.alertOnEnter !== false ? "checked" : "";
        const exit = zone.alertOnExit !== false ? "checked" : "";
        return `
          <div class="geofence-zone-row" data-index="${{index}}">
            <input type="hidden" class="zone-id" value="${{escapeAttr(zone.id || uid())}}">
            <input type="hidden" class="zone-lat" value="${{lat}}">
            <input type="hidden" class="zone-lng" value="${{lng}}">
            <input type="hidden" class="zone-radius" value="${{radius}}">
            <div class="row g-2 align-items-end">
              <div class="col-md-4">
                <label class="form-label small fw-bold">Label</label>
                <input class="form-control zone-label-input" value="${{escapeAttr(label)}}">
              </div>
              <div class="col-md-4">
                <label class="form-label small fw-bold">Center</label>
                <div class="form-control-plaintext small zone-coords-display">${{Number(lat).toFixed(5)}}, ${{Number(lng).toFixed(5)}} · ${{Math.round(radius)}} m radius</div>
              </div>
              <div class="col-md-2">
                <button type="button" class="btn btn-outline-primary btn-sm w-100 zone-edit-map-btn">Edit on map</button>
              </div>
              <div class="col-md-2 text-end">
                <button type="button" class="btn btn-outline-danger btn-sm zone-remove-btn" title="Remove">×</button>
              </div>
            </div>
            <div class="row g-2 mt-2">
              <div class="col-md-6">
                <div class="form-check">
                  <input class="form-check-input zone-alert-enter" type="checkbox" ${{enter}}>
                  <label class="form-check-label small">Email when device enters area</label>
                </div>
              </div>
              <div class="col-md-6">
                <div class="form-check">
                  <input class="form-check-input zone-alert-exit" type="checkbox" ${{exit}}>
                  <label class="form-check-label small">Email when device leaves area</label>
                </div>
              </div>
            </div>
          </div>`;
      }}

      function escapeAttr(value) {{
        return String(value || "")
          .replace(/&/g, "&amp;")
          .replace(/"/g, "&quot;")
          .replace(/</g, "&lt;");
      }}

      function readWifiRows() {{
        const rows = document.querySelectorAll("#wifi-networks .wifi-network-row");
        const networks = [];
        rows.forEach((row) => {{
          const ssid = row.querySelector(".wifi-ssid-input")?.value?.trim();
          if (!ssid) return;
          networks.push({{
            ssid,
            alertOnConnect: row.querySelector(".wifi-alert-connect")?.checked !== false,
            alertOnDisconnect: row.querySelector(".wifi-alert-disconnect")?.checked !== false,
          }});
        }});
        return networks;
      }}

      function readZoneRows() {{
        const rows = document.querySelectorAll("#location-zones .geofence-zone-row");
        const zones = [];
        rows.forEach((row) => {{
          const lat = parseFloat(row.querySelector(".zone-lat")?.value);
          const lng = parseFloat(row.querySelector(".zone-lng")?.value);
          if (Number.isNaN(lat) || Number.isNaN(lng)) return;
          zones.push({{
            id: row.querySelector(".zone-id")?.value || uid(),
            label: row.querySelector(".zone-label-input")?.value?.trim() || "Zone",
            latitude: lat,
            longitude: lng,
            radiusMeters: parseFloat(row.querySelector(".zone-radius")?.value) || 200,
            alertOnEnter: row.querySelector(".zone-alert-enter")?.checked !== false,
            alertOnExit: row.querySelector(".zone-alert-exit")?.checked !== false,
          }});
        }});
        return zones;
      }}

      function syncHiddenJson() {{
        const payload = {{
          wifiNetworks: readWifiRows(),
          locationZones: readZoneRows(),
        }};
        document.getElementById("geofenceJson").value = JSON.stringify(payload);
      }}

      function renderWifiNetworks(networks) {{
        const container = document.getElementById("wifi-networks");
        const list = networks && networks.length ? networks : [{{ ssid: "", alertOnConnect: true, alertOnDisconnect: true }}];
        container.innerHTML = list.map((entry, index) => wifiRowHtml(entry, index)).join("");
        bindWifiEvents();
      }}

      function renderZones(zones) {{
        const container = document.getElementById("location-zones");
        container.innerHTML = (zones || []).map((zone, index) => zoneRowHtml(zone, index)).join("");
        bindZoneEvents();
      }}

      function bindWifiEvents() {{
        document.querySelectorAll(".wifi-remove-btn").forEach((btn) => {{
          btn.onclick = () => {{
            btn.closest(".wifi-network-row")?.remove();
            syncHiddenJson();
          }};
        }});
        document.querySelectorAll(".wifi-ssid-input, .wifi-alert-connect, .wifi-alert-disconnect").forEach((el) => {{
          el.addEventListener("change", syncHiddenJson);
          el.addEventListener("input", syncHiddenJson);
        }});
      }}

      function updateZoneCoordsDisplay(row) {{
        const lat = row.querySelector(".zone-lat")?.value;
        const lng = row.querySelector(".zone-lng")?.value;
        const radius = row.querySelector(".zone-radius")?.value;
        const display = row.querySelector(".zone-coords-display");
        if (display) {{
          display.textContent = `${{Number(lat).toFixed(5)}}, ${{Number(lng).toFixed(5)}} · ${{Math.round(radius)}} m radius`;
        }}
      }}

      function bindZoneEvents() {{
        document.querySelectorAll(".zone-remove-btn").forEach((btn) => {{
          btn.onclick = () => {{
            btn.closest(".geofence-zone-row")?.remove();
            syncHiddenJson();
          }};
        }});
        document.querySelectorAll(".zone-edit-map-btn").forEach((btn) => {{
          btn.onclick = () => {{
            const row = btn.closest(".geofence-zone-row");
            const rows = Array.from(document.querySelectorAll("#location-zones .geofence-zone-row"));
            editingZoneIndex = rows.indexOf(row);
            openZoneMapModal(row);
          }};
        }});
        document.querySelectorAll(".zone-label-input, .zone-alert-enter, .zone-alert-exit").forEach((el) => {{
          el.addEventListener("change", syncHiddenJson);
        }});
      }}

      function ensureModalMap(lat, lng, radius) {{
        const mapEl = document.getElementById("geofence-zone-map");
        if (!modalMap) {{
          modalMap = L.map(mapEl).setView([lat, lng], 15);
          L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap"
          }}).addTo(modalMap);
          modalMap.on("click", (event) => {{
            placeModalMarker(event.latlng.lat, event.latlng.lng, getModalRadius());
          }});
        }} else {{
          modalMap.setView([lat, lng], modalMap.getZoom());
          setTimeout(() => modalMap.invalidateSize(), 200);
        }}
        placeModalMarker(lat, lng, radius);
      }}

      function getModalRadius() {{
        const slider = document.getElementById("geofence-radius-slider");
        return parseInt(slider?.value || "200", 10);
      }}

      function placeModalMarker(lat, lng, radius) {{
        const point = [lat, lng];
        if (!modalMarker) {{
          modalMarker = L.marker(point, {{ draggable: true }}).addTo(modalMap);
          modalMarker.on("dragend", () => {{
            const pos = modalMarker.getLatLng();
            updateModalCircle(pos.lat, pos.lng, getModalRadius());
          }});
        }} else {{
          modalMarker.setLatLng(point);
        }}
        updateModalCircle(lat, lng, radius);
      }}

      function updateModalCircle(lat, lng, radius) {{
        const point = [lat, lng];
        if (!modalCircle) {{
          modalCircle = L.circle(point, {{ radius, color: "#1565c0", fillColor: "#42a5f5", fillOpacity: 0.25 }}).addTo(modalMap);
        }} else {{
          modalCircle.setLatLng(point);
          modalCircle.setRadius(radius);
        }}
        document.getElementById("geofence-radius-label").textContent = radius + " m";
      }}

      function openZoneMapModal(row) {{
        const lat = parseFloat(row.querySelector(".zone-lat")?.value) || defaultCenter[0];
        const lng = parseFloat(row.querySelector(".zone-lng")?.value) || defaultCenter[1];
        const radius = parseInt(row.querySelector(".zone-radius")?.value || "200", 10);
        const slider = document.getElementById("geofence-radius-slider");
        slider.value = radius;
        document.getElementById("geofence-radius-label").textContent = radius + " m";
        const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById("geofence-map-modal"));
        modal.show();
        setTimeout(() => {{
          ensureModalMap(lat, lng, radius);
          modalMap.invalidateSize();
        }}, 350);
        slider.oninput = () => {{
          const value = getModalRadius();
          document.getElementById("geofence-radius-label").textContent = value + " m";
          if (modalMarker) {{
            const pos = modalMarker.getLatLng();
            updateModalCircle(pos.lat, pos.lng, value);
          }}
        }};
        document.getElementById("geofence-map-apply").onclick = () => {{
          if (!modalMarker || editingZoneIndex == null) return;
          const pos = modalMarker.getLatLng();
          const rows = document.querySelectorAll("#location-zones .geofence-zone-row");
          const target = rows[editingZoneIndex];
          if (!target) return;
          target.querySelector(".zone-lat").value = pos.lat;
          target.querySelector(".zone-lng").value = pos.lng;
          target.querySelector(".zone-radius").value = getModalRadius();
          updateZoneCoordsDisplay(target);
          syncHiddenJson();
          modal.hide();
        }};
      }}

      document.getElementById("add-wifi-btn").addEventListener("click", () => {{
        const container = document.getElementById("wifi-networks");
        const index = container.querySelectorAll(".wifi-network-row").length;
        container.insertAdjacentHTML("beforeend", wifiRowHtml({{ ssid: "", alertOnConnect: true, alertOnDisconnect: true }}, index));
        bindWifiEvents();
        syncHiddenJson();
      }});

      document.getElementById("add-zone-btn").addEventListener("click", () => {{
        const container = document.getElementById("location-zones");
        const index = container.querySelectorAll(".geofence-zone-row").length;
        const zone = {{
          id: uid(),
          label: "Zone " + (index + 1),
          latitude: defaultCenter[0],
          longitude: defaultCenter[1],
          radiusMeters: 200,
          alertOnEnter: true,
          alertOnExit: true,
        }};
        container.insertAdjacentHTML("beforeend", zoneRowHtml(zone, index));
        bindZoneEvents();
        syncHiddenJson();
        const rows = container.querySelectorAll(".geofence-zone-row");
        const newRow = rows[rows.length - 1];
        editingZoneIndex = rows.length - 1;
        openZoneMapModal(newRow);
      }});

      document.getElementById("geofence-form").addEventListener("submit", () => syncHiddenJson());

      renderWifiNetworks(initialConfig.wifiNetworks || []);
      renderZones(initialConfig.locationZones || []);
      syncHiddenJson();
    }})();
    </script>
    """
