import { Search, Sun, Moon, Bell, ChevronDown, Menu } from "lucide-react";

type TopBarUser = { email: string; display_name: string | null } | null;

export default function TopBar({dark,setDark,onMenuClick,user,onLogout}:{dark:boolean;setDark:(v:boolean)=>void;onMenuClick?:()=>void;user?:TopBarUser;onLogout?:()=>void}) {
 const name = user?.display_name || user?.email?.split("@")[0] || "Investigator";
 const initial = (name[0] || "A").toUpperCase();
  return <header className="h-[72px] shrink-0 bg-card border-b border-border flex items-center justify-between gap-3 px-4 sm:px-5 md:px-8">
    <button onClick={onMenuClick} className="lg:hidden h-9 w-9 -ml-1 shrink-0 rounded-lg hover:bg-soft flex items-center justify-center text-ink" aria-label="Open menu"><Menu size={20}/></button>
    <div className="relative w-full max-w-[440px]"><Search size={17} className="absolute left-4 top-1/2 -translate-y-1/2 text-faint"/><input className="w-full h-10 rounded-full bg-[#EEF1ED] border-0 pl-11 pr-4 text-[12.5px] outline-none focus:ring-2 focus:ring-brand/20" placeholder="Search investigations, evidence, or keywords..."/></div>
    <div className="flex items-center gap-2 sm:gap-3 ml-auto sm:ml-4 shrink-0">
      <button onClick={()=>setDark(!dark)} className="h-9 w-16 rounded-full bg-[#EEF1ED] flex items-center justify-between px-2 text-muted shrink-0" title="Toggle theme"><Sun size={15}/><span className={`h-6 w-6 rounded-full bg-brand flex items-center justify-center text-white transition-transform ${dark?"translate-x-0":"-translate-x-0"}`}>{dark?<Moon size={13}/>:<Sun size={13}/>}</span></button>
      <button className="h-9 w-9 rounded-full hover:bg-soft flex items-center justify-center text-muted shrink-0"><Bell size={18}/></button>
      <div className="hidden sm:flex items-center gap-2 pl-2 border-l border-border"><div className="h-9 w-9 rounded-full bg-brand text-white flex items-center justify-center font-display">{initial}</div><div className="leading-tight"><p className="text-[12.5px] font-semibold">{name}</p><p className="text-[10.5px] text-muted">{user?.email ?? "Not signed in"}</p></div>{onLogout && <button onClick={onLogout} title="Sign out" className="ml-1 text-[11px] text-muted hover:text-ink underline">Sign out</button>}<ChevronDown size={15} className="text-muted"/></div>
    </div>
  </header>
}
