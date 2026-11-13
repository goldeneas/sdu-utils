import type { ReactNode } from "react";
import data from "../cv.json";
import type { CV } from "./types";

const cv = data as CV;

const stripProtocol = (url: string) =>
  url.replace(/^https?:\/\//, "").replace(/\/$/, "");

function dateRange(start?: string, end?: string) {
  if (!start && !end) return "";
  if (!end || start === end) return start ?? end ?? "";
  if (!start) return end;
  return `${start} - ${end}`;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="section">
      <h2 className="section-title">{title}</h2>
      {children}
    </section>
  );
}

function Bullets({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="bullets">
      {items.map((b, i) => (
        <li key={i}>{b}</li>
      ))}
    </ul>
  );
}

export default function App() {
  const { basics, experience, projects, education, coursework = [], skills, languages } = cv;

  const contacts: { label: string; href?: string }[] = [
    { label: basics.email, href: `mailto:${basics.email}` },
    basics.linkedin ? { label: stripProtocol(basics.linkedin), href: basics.linkedin } : null,
    basics.github ? { label: stripProtocol(basics.github), href: basics.github } : null,
    basics.website ? { label: stripProtocol(basics.website), href: basics.website } : null,
  ].filter(Boolean) as { label: string; href?: string }[];

  return (
    <>
      <nav className="download-bar" aria-label="Download CV">
        <div>
          <strong>cv-maker</strong>
          <span className="download-hint">{basics.name} · Curriculum vitae</span>
        </div>
        <a className="download-button" href="./Nicola_Picarella_CV.pdf" download="Nicola_Picarella_CV.pdf">
          Scarica CV <span>(PDF)</span>
        </a>
      </nav>
      <main className="sheet">
        <header className="header">
          <h1 className="name">{basics.name}</h1>
          <p className="title">{basics.title}</p>
          <p className="location">{basics.location}</p>
          <p className="contacts">
            {contacts.map((c, i) => (
              <span key={i}>
                {i > 0 && <span className="sep"> | </span>}
                {c.href ? <a href={c.href}>{c.label}</a> : c.label}
              </span>
            ))}
          </p>
        </header>

        {basics.summary && (
          <Section title="Summary">
            <p className="summary">{basics.summary}</p>
          </Section>
        )}

        {experience.length > 0 && (
          <Section title="Work Experience">
            {experience.map((e, i) => (
              <article className="entry" key={i}>
                <div className="entry-head">
                  <span className="entry-title">
                    {e.role}, {e.company}
                  </span>
                  <span className="entry-date">{dateRange(e.start, e.end)}</span>
                </div>
                {e.location && <div className="entry-sub">{e.location}</div>}
                <Bullets items={e.bullets} />
              </article>
            ))}
          </Section>
        )}

        {projects.length > 0 && (
          <Section title="Projects">
            {projects.map((p, i) => (
              <article className="entry" key={i}>
                <div className="entry-head">
                  <span className="entry-title">
                    {p.name}
                    {p.tagline && <span className="tagline"> - {p.tagline}</span>}
                  </span>
                  <span className="entry-date">{dateRange(p.start, p.end)}</span>
                </div>
                {p.link && (
                  <div className="entry-sub">
                    <a href={p.link}>{stripProtocol(p.link)}</a>
                  </div>
                )}
                <Bullets items={p.bullets} />
              </article>
            ))}
          </Section>
        )}

        {education.length > 0 && (
          <Section title="Education">
            {education.map((e, i) => (
              <article className="entry" key={i}>
                <div className="entry-head">
                  <span className="entry-title">{e.degree}</span>
                  <span className="entry-date">{dateRange(e.start, e.end)}</span>
                </div>
                <div className="entry-sub">
                  {e.institution}
                  {e.location ? `, ${e.location}` : ""}
                </div>
                <Bullets items={e.bullets} />
              </article>
            ))}
            {coursework.length > 0 && (
              <article className="entry">
                <div className="entry-head">
                  <span className="entry-title">Relevant Coursework</span>
                </div>
                <Bullets items={coursework} />
              </article>
            )}
          </Section>
        )}

        {skills.length > 0 && (
          <Section title="Key Skills">
            <dl className="skills">
              {skills.map((g, i) => (
                <div className="skill-row" key={i}>
                  <dt>{g.group}</dt>
                  <dd>{g.items.join(", ")}</dd>
                </div>
              ))}
            </dl>
          </Section>
        )}

        {languages.length > 0 && (
          <Section title="Languages">
            <dl className="skills">
              {languages.map((l, i) => (
                <div className="skill-row" key={i}>
                  <dt>{l.name}</dt>
                  <dd>{l.level}</dd>
                </div>
              ))}
            </dl>
          </Section>
        )}
      </main>
    </>
  );
}
