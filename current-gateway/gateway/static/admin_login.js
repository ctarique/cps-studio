"use strict";
const form=document.getElementById("admin-login");
const credential=document.getElementById("admin-credential");
const result=document.getElementById("login-result");
const submit=document.getElementById("sign-in");
form.addEventListener("submit",async event=>{
  event.preventDefault();
  if(!form.reportValidity())return;
  submit.disabled=true;
  result.textContent="Signing in…";
  const token=credential.value;
  credential.value="";
  try{
    const response=await fetch("/api/admin/session",{method:"POST",credentials:"same-origin",cache:"no-store",
      headers:{"Content-Type":"application/json","X-Sentinel-Token":token},body:"{}"});
    if(response.ok){location.replace("/admin");return;}
    result.textContent=response.status===429?"Too many sign-in attempts. Try again in one minute.":"Sign-in failed. Check your instructor credential.";
  }catch{result.textContent="Gateway unavailable. Please try again when the connection returns.";}
  finally{submit.disabled=false;}
});
