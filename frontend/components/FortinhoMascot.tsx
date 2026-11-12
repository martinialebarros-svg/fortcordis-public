import { type CSSProperties } from "react";

export type FortinhoMood = "happy" | "excited" | "thinking" | "alert";
export type FortinhoGesture = "idle" | "wave" | "open-arms" | "point-right";

interface FortinhoMascotProps {
  mood?: FortinhoMood;
  gesture?: FortinhoGesture;
  message?: string;
  className?: string;
}

const ARM_LEFT_ORIGIN: CSSProperties = { transformOrigin: "106px 126px" };
const ARM_RIGHT_ORIGIN: CSSProperties = { transformOrigin: "174px 126px" };
const LEG_LEFT_ORIGIN: CSSProperties = { transformOrigin: "118px 204px" };
const LEG_RIGHT_ORIGIN: CSSProperties = { transformOrigin: "162px 204px" };

function renderFace(mood: FortinhoMood) {
  if (mood === "excited") {
    return (
      <>
        <path d="M108 120l4 2 4-2-2 4 2 4-4-2-4 2 2-4z" fill="#0f172a" />
        <path d="M164 120l4 2 4-2-2 4 2 4-4-2-4 2 2-4z" fill="#0f172a" />
        <circle cx="112" cy="127" r="2.8" fill="#0f172a" />
        <circle cx="168" cy="127" r="2.8" fill="#0f172a" />
        <path
          d="M114 150c6 13 20 19 26 19s20-6 26-19"
          fill="none"
          stroke="#7f1d1d"
          strokeLinecap="round"
          strokeWidth="5.5"
        />
      </>
    );
  }

  if (mood === "thinking") {
    return (
      <>
        <path d="M104 112c4-4 10-5 16-3" fill="none" stroke="#0f172a" strokeLinecap="round" strokeWidth="4" />
        <path d="M158 109c5-4 12-4 17 0" fill="none" stroke="#0f172a" strokeLinecap="round" strokeWidth="4" />
        <circle className="fortinho-eye" cx="114" cy="125" r="6" fill="#0f172a" />
        <ellipse className="fortinho-eye" cx="168" cy="126" rx="6" ry="4.8" fill="#0f172a" />
        <path d="M124 154c8-4 18-4 25 0" fill="none" stroke="#7f1d1d" strokeLinecap="round" strokeWidth="5" />
      </>
    );
  }

  if (mood === "alert") {
    return (
      <>
        <path d="M102 111c6-5 14-6 21-2" fill="none" stroke="#0f172a" strokeLinecap="round" strokeWidth="4.2" />
        <path d="M156 109c7-5 15-4 21 2" fill="none" stroke="#0f172a" strokeLinecap="round" strokeWidth="4.2" />
        <circle className="fortinho-eye" cx="114" cy="126" r="7" fill="#0f172a" />
        <circle className="fortinho-eye" cx="168" cy="126" r="7" fill="#0f172a" />
        <path d="M124 155h34" fill="none" stroke="#7f1d1d" strokeLinecap="round" strokeWidth="5.5" />
        <path
          d="M188 93l6 10 6-10m-6 12v8"
          fill="none"
          stroke="#7f1d1d"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3"
        />
      </>
    );
  }

  return (
    <>
      <circle className="fortinho-eye" cx="114" cy="126" r="6.5" fill="#0f172a" />
      <circle className="fortinho-eye" cx="168" cy="126" r="6.5" fill="#0f172a" />
      <path
        d="M114 151c6 11 18 16 26 16s20-5 26-16"
        fill="none"
        stroke="#7f1d1d"
        strokeLinecap="round"
        strokeWidth="5.5"
      />
    </>
  );
}

export default function FortinhoMascot({
  mood = "happy",
  gesture = "wave",
  message = "Ola! Eu sou o Fortinho. Posso conversar com voce com mais carisma e clareza.",
  className = "",
}: FortinhoMascotProps) {
  const armLeftClass = gesture === "open-arms" ? "fortinho-arm-left-open" : "fortinho-arm-left-idle";
  const armRightClass =
    gesture === "wave"
      ? "fortinho-arm-right-wave"
      : gesture === "open-arms"
      ? "fortinho-arm-right-open"
      : gesture === "point-right"
      ? "fortinho-arm-right-point"
      : "fortinho-arm-right-idle";
  const legLeftClass = mood === "excited" ? "fortinho-leg-left-hop" : "fortinho-leg-left-idle";
  const legRightClass = mood === "excited" ? "fortinho-leg-right-hop" : "fortinho-leg-right-idle";
  const bodyAnimationClass = mood === "excited" ? "fortinho-bob-fast" : "fortinho-bob";

  return (
    <div className={`w-[228px] select-none ${className}`} data-fortcordis-overlay-safe="1">
      <div className="relative mb-2 rounded-2xl border border-rose-200 bg-white/95 px-3 py-2 shadow-xl backdrop-blur-sm">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-rose-500">Fortinho</p>
        <p className="text-sm leading-5 text-slate-700">{message}</p>
        <span className="absolute -bottom-2 right-7 h-4 w-4 rotate-45 border-b border-r border-rose-200 bg-white" />
      </div>

      <svg
        aria-label={`Mascote Fortinho em estado ${mood} fazendo gesto ${gesture}`}
        role="img"
        viewBox="0 0 280 280"
        className="h-[192px] w-[228px] drop-shadow-[0_18px_26px_rgba(15,23,42,0.22)]"
      >
        <defs>
          <linearGradient id="fortinhoHeartGradient" x1="62" y1="54" x2="220" y2="194" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#fb7185" />
            <stop offset="45%" stopColor="#f43f5e" />
            <stop offset="100%" stopColor="#be123c" />
          </linearGradient>
        </defs>

        <g className={bodyAnimationClass}>
          <ellipse cx="140" cy="255" rx="60" ry="10" fill="#cbd5e1" opacity="0.7" />

          <g className={legLeftClass} style={LEG_LEFT_ORIGIN}>
            <path d="M118 203c-6 16-8 24-7 33" fill="none" stroke="#334155" strokeLinecap="round" strokeWidth="10" />
            <path d="M105 236h22" fill="none" stroke="#1e293b" strokeLinecap="round" strokeWidth="8" />
          </g>
          <g className={legRightClass} style={LEG_RIGHT_ORIGIN}>
            <path d="M162 203c6 16 8 24 7 33" fill="none" stroke="#334155" strokeLinecap="round" strokeWidth="10" />
            <path d="M151 236h23" fill="none" stroke="#1e293b" strokeLinecap="round" strokeWidth="8" />
          </g>

          <g className={armLeftClass} style={ARM_LEFT_ORIGIN}>
            <path d="M106 126c-23-3-34-8-48-20" fill="none" stroke="#334155" strokeLinecap="round" strokeWidth="10" />
            <circle cx="58" cy="106" r="8" fill="#334155" />
          </g>
          <g className={armRightClass} style={ARM_RIGHT_ORIGIN}>
            <path d="M174 126c24-2 35-8 49-20" fill="none" stroke="#334155" strokeLinecap="round" strokeWidth="10" />
            <circle cx="223" cy="106" r="8" fill="#334155" />
          </g>

          <path
            d="M140 84c0-25-35-43-61-21-26 23-18 67 61 125 79-58 87-102 61-125-26-22-61-4-61 21z"
            fill="url(#fortinhoHeartGradient)"
            stroke="#9f1239"
            strokeLinejoin="round"
            strokeWidth="6"
          />
          <path
            d="M140 99c0-11-15-18-26-9-11 10-8 28 26 55 34-27 37-45 26-55-11-9-26-2-26 9z"
            fill="#fecdd3"
            opacity="0.35"
          />
          <ellipse cx="96" cy="148" rx="13" ry="8" fill="#fb7185" opacity="0.32" />
          <ellipse cx="184" cy="148" rx="13" ry="8" fill="#fb7185" opacity="0.32" />

          {renderFace(mood)}
        </g>
      </svg>
    </div>
  );
}
