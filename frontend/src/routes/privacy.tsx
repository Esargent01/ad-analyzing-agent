import { Link } from "react-router-dom";

export function PrivacyRoute() {
  return (
    <div className="mx-auto max-w-2xl px-5 py-12" style={{ fontFamily: "'Outfit', sans-serif" }}>
      <header className="mb-8">
        <h1 className="mb-1 text-2xl font-semibold">Privacy Policy</h1>
        <p className="text-xs text-[var(--text-tertiary)]">
          Effective date: April 13, 2026
        </p>
      </header>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">1. What we do</h2>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          Ad Creative Agent (&ldquo;the Service&rdquo;) is an ad optimization
          platform that helps advertisers test creative variants across Meta
          (Facebook/Instagram) and Google Ads. The Service monitors campaign
          performance, analyzes results, and generates optimized creative
          combinations.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">2. Data we collect</h2>
        <p className="mb-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          When you use the Service, we collect and store:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-sm text-[var(--text-secondary)]">
          <li>
            <strong className="text-[var(--text)]">Account information</strong>{" "}
            &mdash; your email address, used for authentication via magic-link
            sign-in.
          </li>
          <li>
            <strong className="text-[var(--text)]">Meta connection data</strong>{" "}
            &mdash; when you connect your Meta account, we receive an OAuth
            access token, your Meta user ID, and a list of ad accounts and Pages
            you have access to. We use this to manage ads on your behalf.
          </li>
          <li>
            <strong className="text-[var(--text)]">
              Ad campaign metrics
            </strong>{" "}
            &mdash; impressions, reach, clicks, spend, CTR, CPC, and CPM for
            campaigns you import into the Service.
          </li>
          <li>
            <strong className="text-[var(--text)]">Creative elements</strong>{" "}
            &mdash; headlines, subheads, CTAs, media asset references, and
            audience segments that make up your ad creative variants.
          </li>
        </ul>
        <p className="mb-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          We do <strong className="text-[var(--text)]">not</strong> collect or
          store:
        </p>
        <ul className="list-disc space-y-2 pl-6 text-sm text-[var(--text-secondary)]">
          <li>
            Personal data about people who see or interact with your ads
          </li>
          <li>Payment or billing information from ad platforms</li>
          <li>
            Data from your Meta account beyond what is needed to manage ad
            campaigns
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">
          3. How we store and protect your data
        </h2>
        <ul className="list-disc space-y-2 pl-6 text-sm text-[var(--text-secondary)]">
          <li>
            <strong className="text-[var(--text)]">OAuth tokens</strong> are
            encrypted at rest using Fernet symmetric encryption before being
            stored in our database. The encryption key is stored separately from
            the database and is never committed to source control.
          </li>
          <li>
            <strong className="text-[var(--text)]">Session cookies</strong> are
            HttpOnly, Secure, and SameSite-protected. Mutating API requests
            require a matching CSRF token (double-submit cookie pattern).
          </li>
          <li>
            <strong className="text-[var(--text)]">Database access</strong> is
            restricted to the application service and is not publicly accessible.
          </li>
          <li>
            <strong className="text-[var(--text)]">Magic-link tokens</strong>{" "}
            are single-use, time-limited (15 minutes), and hashed before
            storage.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">4. How we use your data</h2>
        <p className="mb-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          We use the data we collect solely to:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-sm text-[var(--text-secondary)]">
          <li>Authenticate you and manage your account session</li>
          <li>Read ad campaign metrics from connected platforms</li>
          <li>
            Analyze creative performance and generate optimization insights
          </li>
          <li>
            Propose new creative variants for your review and approval
          </li>
          <li>
            Execute approved actions (pause, scale, launch) on your ad campaigns
          </li>
          <li>Send you daily and weekly performance reports</li>
        </ul>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          We do <strong className="text-[var(--text)]">not</strong> sell, rent,
          or share your data with third parties for advertising or marketing
          purposes.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">5. Third-party services</h2>
        <p className="mb-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          The Service integrates with:
        </p>
        <ul className="list-disc space-y-2 pl-6 text-sm text-[var(--text-secondary)]">
          <li>
            <strong className="text-[var(--text)]">
              Meta (Facebook) Marketing API
            </strong>{" "}
            &mdash; to read metrics and manage ad campaigns. Governed by{" "}
            <a
              href="https://www.facebook.com/privacy/policy/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--accent)] hover:underline"
            >
              Meta&apos;s Privacy Policy
            </a>
            .
          </li>
          <li>
            <strong className="text-[var(--text)]">
              Anthropic (Claude API)
            </strong>{" "}
            &mdash; to generate creative variant suggestions. Prompts sent to
            the LLM contain creative elements and anonymized performance data;
            no personally identifiable information is sent.
          </li>
          <li>
            <strong className="text-[var(--text)]">SendGrid</strong> &mdash; to
            send authentication emails and performance reports to your email
            address.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">6. Data retention</h2>
        <ul className="list-disc space-y-2 pl-6 text-sm text-[var(--text-secondary)]">
          <li>
            <strong className="text-[var(--text)]">Campaign metrics</strong> are
            retained for the lifetime of the campaign plus 90 days after
            deletion.
          </li>
          <li>
            <strong className="text-[var(--text)]">Meta OAuth tokens</strong>{" "}
            expire after approximately 60 days. Expired tokens are not usable
            and are overwritten when you reconnect.
          </li>
          <li>
            <strong className="text-[var(--text)]">Session data</strong> expires
            after 30 days of inactivity.
          </li>
          <li>
            <strong className="text-[var(--text)]">Magic-link tokens</strong>{" "}
            expire after 15 minutes and are deleted after use.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">7. Data deletion</h2>
        <p className="mb-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          You can delete your data at any time:
        </p>
        <ul className="list-disc space-y-2 pl-6 text-sm text-[var(--text-secondary)]">
          <li>
            <strong className="text-[var(--text)]">Disconnect Meta</strong>{" "}
            &mdash; click &ldquo;Disconnect&rdquo; in the dashboard to
            immediately delete your stored OAuth token and connection data.
          </li>
          <li>
            <strong className="text-[var(--text)]">
              Remove from Facebook
            </strong>{" "}
            &mdash; remove this app from your{" "}
            <a
              href="https://www.facebook.com/settings?tab=business_tools"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--accent)] hover:underline"
            >
              Facebook Business Integrations
            </a>{" "}
            settings. We will automatically receive a deauthorization callback
            and delete your connection data.
          </li>
          <li>
            <strong className="text-[var(--text)]">Account deletion</strong>{" "}
            &mdash; contact us at the email below to request full deletion of
            your account and all associated data.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">8. Your rights</h2>
        <p className="mb-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          You have the right to:
        </p>
        <ul className="list-disc space-y-2 pl-6 text-sm text-[var(--text-secondary)]">
          <li>Access the data we hold about you</li>
          <li>Request correction of inaccurate data</li>
          <li>Request deletion of your data</li>
          <li>Disconnect third-party integrations at any time</li>
          <li>Export your campaign data</li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">9. Contact</h2>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          For privacy-related questions or data requests, contact us at:{" "}
          <a
            href="mailto:adagent@company.com"
            className="text-[var(--accent)] hover:underline"
          >
            adagent@company.com
          </a>
        </p>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-lg font-medium">
          10. Changes to this policy
        </h2>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          We may update this policy from time to time. If we make material
          changes, we will notify you via the email address associated with your
          account.
        </p>
      </section>

      <footer className="border-t border-[var(--border)] pt-6 text-xs text-[var(--text-tertiary)]">
        <Link to="/sign-in" className="hover:underline">
          Sign in
        </Link>
      </footer>
    </div>
  );
}
