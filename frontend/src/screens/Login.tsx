import { useState } from "react";
import { ArrowRight, ShieldCheck, Network, FileText, Lock, Loader2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export default function Login({onLogin,onBack}:{onLogin:()=>void;onBack:()=>void}) {
 const { login, register } = useAuth();
 const [mode,setMode]=useState<"login"|"register">("login");
 const [email,setEmail]=useState("demo@lineage.app");
 const [password,setPassword]=useState("demo-access");
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState<string|null>(null);

 // Real auth against the backend. The demo credentials are pre-filled so a
 // live demo needs no typing — but they now create/sign in to an actual
 // account rather than waving the user through.
 async function submit(e:React.FormEvent){
  e.preventDefault();
  setBusy(true); setError(null);
  try {
   if (mode==="register") { await register(email,password); }
   else {
    try { await login(email,password); }
    catch (err:any) {
     // First run against a fresh database has no accounts yet — rather than
     // dead-ending a demo on "incorrect password", register the demo account
     // automatically and continue. Real typo'd logins still surface normally.
     if (email==="demo@lineage.app") { await register(email,password); }
     else throw err;
    }
   }
   onLogin();
  } catch (err:any) {
   setError(err?.message ?? "Could not sign in.");
  } finally { setBusy(false); }
 }

 return <div className="min-h-screen grid lg:grid-cols-2 bg-bg">
  <section className="hidden lg:flex bg-brandDark text-white p-12 xl:p-16 flex-col justify-between relative overflow-hidden"><div><button onClick={onBack} className="font-display text-[29px] tracking-[.18em]">LINEAGE</button><p className="text-[9px] tracking-[.15em] text-white/55 mt-1">TRACE TRUTH. PROTECT PEOPLE.</p><div className="h-px w-10 bg-white/30 mt-12"/><h1 className="font-display text-[52px] leading-[1.02] max-w-lg mt-12">A safer digital world starts with the truth.</h1><p className="text-[15px] text-white/65 max-w-lg leading-relaxed mt-6">LINEAGE helps you detect manipulated media, trace its origin, and build evidence with the power of AI — so you can act with confidence.</p><div className="space-y-5 mt-10">{[[ShieldCheck,"Detect","Identify AI-manipulated media"],[Network,"Trace","Visualize how it spreads"],[FileText,"Build Evidence","Collect and secure forensic insights"],[Lock,"Take Action","Generate reports and support investigations"]].map(([I,t,d]:any)=><div className="flex gap-4" key={t}><div className="h-10 w-10 rounded-full bg-white/10 flex items-center justify-center"><I size={19}/></div><div><p className="text-[13px] font-semibold">{t}</p><p className="text-[11px] text-white/55 mt-1">{d}</p></div></div>)}</div></div><p className="font-display italic text-[16px] text-white/60">Technology for a more truthful tomorrow.</p></section>
  <section className="flex items-center justify-center p-6 md:p-12"><div className="w-full max-w-[520px]"><div className="flex justify-between items-center mb-8"><button onClick={onBack} className="lg:hidden font-display text-[23px] tracking-[.15em]">LINEAGE</button><div className="ml-auto text-[12px] text-muted">{mode==="login"?"New here?":"Have an account?"} <button onClick={()=>{setMode(mode==="login"?"register":"login");setError(null)}} className="ml-2 rounded-xl border border-brand text-brand px-4 py-2">{mode==="login"?"Create Account":"Log In"}</button></div></div><div className="bg-card border border-border rounded-3xl p-7 md:p-10 shadow-soft"><div className="text-center"><h2 className="font-display text-[36px]">{mode==="login"?"Welcome back":"Create your account"}</h2><p className="text-[13px] text-muted mt-2">{mode==="login"?"Log in to continue your investigations.":"Set up an account to start investigating."}</p></div>
  <form onSubmit={submit} className="mt-8"><label className="block text-[12px] font-medium mb-2">Email address</label><input value={email} onChange={e=>setEmail(e.target.value)} type="email" required placeholder="you@example.com" className="w-full h-12 rounded-xl border border-border px-4 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"/><div className="flex justify-between mt-5 mb-2"><label className="text-[12px] font-medium">Password</label></div><input value={password} onChange={e=>setPassword(e.target.value)} type="password" required minLength={6} placeholder="Enter your password" className="w-full h-12 rounded-xl border border-border px-4 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"/>
  {error && <p className="mt-4 text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}
  <button disabled={busy} className="w-full h-12 rounded-xl bg-brand text-white mt-6 text-[13px] font-semibold disabled:opacity-60 inline-flex items-center justify-center gap-2">{busy?<><Loader2 size={15} className="animate-spin"/>Signing in…</>:<>{mode==="login"?"Log In":"Create Account"} <ArrowRight size={15}/></>}</button></form>
  <p className="text-center text-[10.5px] text-muted leading-relaxed mt-7">Accounts are real and stored by the LINEAGE backend. By continuing, you agree to our <u>Terms of Service</u> and <u>Privacy Policy</u>.</p></div></div></section>
 </div>
}
