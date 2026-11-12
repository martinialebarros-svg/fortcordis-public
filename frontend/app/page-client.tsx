"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import axios from "axios";
import { rememberSession } from "@/lib/auth-session";
import { safeLoginDestination } from "@/lib/auth-routes";
import {
  Building2,
  Eye,
  EyeOff,
  HeartPulse,
  Loader2,
  LockKeyhole,
  Mail,
  ShieldCheck,
  UserRound,
} from "lucide-react";

const API_URL = "/api/v1";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const formData = new URLSearchParams();
      formData.append("username", email);
      formData.append("password", password);

      const response = await axios.post(`${API_URL}/auth/login`, formData, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        withCredentials: true,
      });

      rememberSession(response.data);

      if (typeof window !== "undefined") {
        window.location.replace(safeLoginDestination(new URLSearchParams(window.location.search).get("next")));
        return;
      }
    } catch (err: unknown) {
      setError(
        axios.isAxiosError(err)
          ? err.response?.data?.detail || "Nao foi possivel entrar no sistema."
          : "Nao foi possivel entrar no sistema.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="fc-login-page">
      <Image
        src="/brand/fortcordis-portal-hero.jpg"
        alt="Atendimento cardiológico veterinário Fort Cordis"
        fill
        priority
        sizes="100vw"
        className="fc-login-background"
      />
      <div className="fc-login-overlay" />

      <div className="fc-login-shell">
        <header className="fc-login-brand">
          <Image src="/brand/fortcordis-logo-oficial.png" alt="Fort Cordis" width={58} height={58} priority />
          <span><strong>FORT CORDIS</strong><small>Cardiologia Veterinária</small></span>
        </header>

        <div className="fc-login-grid">
          <section className="fc-login-intro">
            <span className="fc-login-kicker"><HeartPulse className="h-4 w-4" />Central clínica</span>
            <h1>Fort Cordis</h1>
            <p>Agenda, atendimento, pacientes e laudos em um ambiente clínico integrado.</p>
            <div className="fc-login-trust">
              <span><ShieldCheck className="h-5 w-5" /><strong>Acesso protegido</strong><small>Sessão da equipe interna</small></span>
              <span><LockKeyhole className="h-5 w-5" /><strong>Dados clínicos</strong><small>Operação com rastreabilidade</small></span>
            </div>
          </section>

          <section className="fc-login-panel" aria-labelledby="login-title">
            <div className="fc-login-panel-header">
              <span>Acesso da equipe</span>
              <h2 id="login-title">Entrar no sistema</h2>
              <p>Use seu email institucional e senha cadastrada.</p>
            </div>

            <form className="fc-login-form" onSubmit={handleLogin} aria-busy={loading}>
              {error && <div className="fc-login-error" role="alert">{error}</div>}

              <label htmlFor="email">
                Email
                <span className="fc-login-control">
                  <Mail className="h-5 w-5" />
                  <input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    placeholder="seu@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </span>
              </label>

              <label htmlFor="password">
                Senha
                <span className="fc-login-control">
                  <LockKeyhole className="h-5 w-5" />
                  <input
                    id="password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    placeholder="Digite sua senha"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((current) => !current)}
                    aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                    title={showPassword ? "Ocultar senha" : "Mostrar senha"}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </span>
              </label>

              <button type="submit" disabled={loading} className="fc-login-submit">
                {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <LockKeyhole className="h-5 w-5" />}
                {loading ? "Entrando..." : "Entrar"}
              </button>
            </form>

            <div className="fc-login-portals">
              <p>Outros acessos</p>
              <div>
                <Link href="/area-pacientes"><UserRound className="h-4 w-4" />Portal do tutor</Link>
                <Link href="/clinica-parceira"><Building2 className="h-4 w-4" />Clínica parceira</Link>
              </div>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
