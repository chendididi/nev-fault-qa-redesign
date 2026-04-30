"use client";

import { FormEvent, useEffect, useState } from "react";
import { UserPlus } from "lucide-react";
import { AppShell } from "@/components/shell";
import { api, User } from "@/lib/api";

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"admin" | "technician">("technician");
  const [password, setPassword] = useState("Tech123!");

  async function load() {
    const data = await api<{items: User[]}>("/api/admin/users");
    setUsers(data.items);
  }

  useEffect(() => {
    let active = true;
    async function loadInitial() {
      try {
        const data = await api<{items: User[]}>("/api/admin/users");
        if (active) setUsers(data.items);
      } catch {
        return;
      }
    }
    void loadInitial();
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await api("/api/admin/users", {method: "POST", body: JSON.stringify({email, name, role, password})});
    setEmail("");
    setName("");
    await load();
  }

  return (
    <AppShell>
      <div className="p-6">
        <header className="mb-5">
          <h1 className="text-xl font-semibold">用户管理</h1>
          <p className="mt-1 text-sm text-slate-500">管理员维护系统配置和知识库，技师使用诊断工作台。</p>
        </header>
        <form onSubmit={submit} className="mb-6 grid gap-3 rounded-md border border-line bg-white p-4 md:grid-cols-[1fr_1fr_160px_160px_auto]">
          <input className="h-10 rounded-md border border-line px-3 text-sm" placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input className="h-10 rounded-md border border-line px-3 text-sm" placeholder="姓名" value={name} onChange={(e) => setName(e.target.value)} />
          <select className="h-10 rounded-md border border-line px-3 text-sm" value={role} onChange={(e) => setRole(e.target.value as "admin" | "technician")}>
            <option value="technician">技师</option>
            <option value="admin">管理员</option>
          </select>
          <input className="h-10 rounded-md border border-line px-3 text-sm" value={password} onChange={(e) => setPassword(e.target.value)} />
          <button className="flex h-10 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white">
            <UserPlus className="h-4 w-4" />
            创建
          </button>
        </form>
        <div className="overflow-hidden rounded-md border border-line bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-panel text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3">姓名</th>
                <th className="px-4 py-3">邮箱</th>
                <th className="px-4 py-3">角色</th>
                <th className="px-4 py-3">状态</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-t border-line">
                  <td className="px-4 py-3 font-medium">{user.name}</td>
                  <td className="px-4 py-3 text-slate-600">{user.email}</td>
                  <td className="px-4 py-3">{user.role === "admin" ? "管理员" : "技师"}</td>
                  <td className="px-4 py-3">{user.is_active ? "启用" : "停用"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
