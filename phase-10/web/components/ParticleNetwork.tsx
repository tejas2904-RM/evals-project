"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

type Dot = { x: number; y: number; vx: number; vy: number };

export function ParticleNetwork() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pathname = usePathname() || "/";
  const home = pathname === "/";

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let dots: Dot[] = [];
    let w = 0;
    let h = 0;

    const targetCount = () => Math.min(160, Math.max(36, Math.floor((w * h) / 12000)));

    const seed = () => {
      const n = targetCount();
      dots = Array.from({ length: n }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.32,
        vy: (Math.random() - 0.5) * 0.32,
      }));
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (dots.length === 0 || Math.abs(dots.length - targetCount()) > 24) seed();
    };

    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      const maxDist = 128;
      const maxDist2 = maxDist * maxDist;

      ctx.lineWidth = 1;
      for (let i = 0; i < dots.length; i++) {
        const a = dots[i];
        if (!a) continue;
        for (let j = i + 1; j < dots.length; j++) {
          const b = dots[j];
          if (!b) continue;
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 > maxDist2) continue;
          const alpha = 0.28 * (1 - Math.sqrt(d2) / maxDist);
          ctx.strokeStyle = `rgba(125, 206, 168, ${alpha})`;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      for (const d of dots) {
        ctx.fillStyle = "rgba(210, 240, 222, 0.9)";
        ctx.beginPath();
        ctx.arc(d.x, d.y, 1.55, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const tick = () => {
      if (!reduced) {
        for (const d of dots) {
          d.x += d.vx;
          d.y += d.vy;
          if (d.x < 0 || d.x > w) d.vx *= -1;
          if (d.y < 0 || d.y > h) d.vy *= -1;
          d.x = Math.min(w, Math.max(0, d.x));
          d.y = Math.min(h, Math.max(0, d.y));
        }
      }
      draw();
      if (!reduced) raf = requestAnimationFrame(tick);
    };

    resize();
    tick();
    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={home ? "pointer-events-none fixed inset-0 z-0 opacity-100" : "pointer-events-none fixed inset-0 z-0 opacity-60"}
    />
  );
}
