import Link from "next/link";
import { AuthActionButton } from "@/features/auth/components/AuthActionButton";

const features = [
  {
    icon: "✦",
    title: "Example Sentences",
    description: "Build vocabulary through context, not isolated words.",
  },
  {
    icon: "✎",
    title: "AI Writing",
    description: "Generate sentences with your target words woven in naturally.",
  },
  {
    icon: "◈",
    title: "Daily Journal",
    description: "Write in English every day and get instant feedback.",
  },
  {
    icon: "⊞",
    title: "Exam Prep",
    description: "Practice with materials tailored to your target certification.",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-amber-50 font-sans">
      {/* Nav */}
      <header className="flex items-center justify-between px-8 py-5 border-b border-amber-200">
        <span className="text-xl font-bold tracking-tight text-amber-900">
          Vicente Calderon
        </span>
        <nav className="hidden sm:flex items-center gap-6 text-sm font-medium text-amber-800">
          <a href="#features" className="hover:text-amber-500 transition-colors">Features</a>
          <a href="#" className="hover:text-amber-500 transition-colors">About</a>
          <Link href="/me" className="hover:text-amber-500 transition-colors">
            My Page
          </Link>
          <AuthActionButton />
        </nav>
      </header>

      {/* Hero */}
      <main>
        <section className="relative flex flex-col items-center justify-center text-center px-6 pt-24 pb-28 overflow-hidden">
          {/* decorative blobs */}
          <div className="pointer-events-none absolute -top-16 -left-16 w-80 h-80 rounded-full bg-amber-300 opacity-30 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-20 -right-16 w-96 h-96 rounded-full bg-yellow-300 opacity-25 blur-3xl" />

          <div className="relative z-10 max-w-2xl">
            <span className="inline-block mb-4 rounded-full border border-amber-300 bg-amber-100 px-4 py-1 text-xs font-semibold uppercase tracking-widest text-amber-700">
              Personalized English Learning
            </span>
            <h1 className="text-5xl sm:text-6xl font-extrabold leading-tight tracking-tight text-amber-950 mb-6">
              Learn English<br />
              <span className="text-amber-500">through context</span>
            </h1>
            <p className="text-lg text-amber-800 leading-relaxed mb-10 max-w-lg mx-auto">
              Stop memorising isolated words. Master English naturally with personalized example sentences built around what you want to say.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <AuthActionButton />
              <Link
                href="/learning-paths"
                className="rounded-full border-2 border-amber-400 px-8 py-4 text-base font-bold text-amber-800 hover:bg-amber-100 transition-colors"
              >
                Explore learning paths
              </Link>
              <Link
                href="/me"
                className="rounded-full border-2 border-amber-200 px-8 py-4 text-base font-bold text-amber-800 hover:bg-amber-100 transition-colors"
              >
                Open My Page
              </Link>
            </div>
          </div>
        </section>

        {/* Features */}
        <section
          id="features"
          className="bg-white border-t border-amber-100 py-20 px-6"
        >
          <div className="max-w-4xl mx-auto">
            <h2 className="text-3xl font-bold text-center text-amber-950 mb-2">
              Everything you need
            </h2>
            <p className="text-center text-amber-700 mb-12">
              One app. Every skill. Powered by AI.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {features.map((f) => (
                <div
                  key={f.title}
                  className="rounded-2xl border border-amber-100 bg-amber-50 p-7 hover:shadow-md transition-shadow"
                >
                  <span className="inline-block text-2xl text-amber-400 mb-4">{f.icon}</span>
                  <h3 className="text-lg font-bold text-amber-950 mb-2">{f.title}</h3>
                  <p className="text-sm text-amber-700 leading-relaxed">{f.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="bg-amber-400 py-20 px-6 text-center">
          <h2 className="text-3xl font-extrabold text-amber-950 mb-4">
            Ready to level up your English?
          </h2>
          <p className="text-amber-900 mb-8 max-w-md mx-auto">
            Join and start building real English fluency today — no credit card required.
          </p>
          <AuthActionButton variant="dark" />
        </section>
      </main>

      {/* Footer */}
      <footer className="bg-amber-50 border-t border-amber-200 px-8 py-6 text-center text-sm text-amber-600">
        © 2026 Vicente Calderon — built with AI, for real learners.
      </footer>
    </div>
  );
}
