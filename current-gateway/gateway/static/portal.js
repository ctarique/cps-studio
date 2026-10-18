"use strict";

function labelMode(mode){
  if(mode === "wifi") return "Physical Wi-Fi";
  if(mode === "simulator_http") return "HTTP simulator";
  if(mode === "simulator") return "Simulator";
  return mode || "Unknown transport";
}

function labelStage(stage){
  return String(stage || "UNKNOWN").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

async function refreshGatewayHealth(){
  const targets=[...document.querySelectorAll("[data-gateway-health]")];
  if(!targets.length) return;
  try{
    const response=await fetch("/api/health", {cache:"no-store"});
    const state=await response.json();
    const text=location.pathname.startsWith("/admin")
      ? (state.locked ? "Locked" : "Unlocked")
      : `${labelMode(state.transport)} · ${state.locked ? "Locked" : "Experiment access enabled"} · ${labelStage(state.stage)}`;
    targets.forEach(el=>{
      el.textContent=text;

      if(location.pathname.startsWith("/admin")){
        el.classList.toggle("gateway-status-locked", Boolean(state.locked));
        el.classList.toggle("gateway-status-unlocked", !state.locked);
      }
    });
    document.body.dataset.gatewayAvailable=response.ok ? "true" : "false";
  }catch{
    targets.forEach(el=>el.textContent="Gateway unavailable · physical state unknown");
    document.body.dataset.gatewayAvailable="false";
  }
}

refreshGatewayHealth();
setInterval(refreshGatewayHealth,5000);
