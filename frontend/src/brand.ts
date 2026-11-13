/**
 * Brand configuration – the single place to adjust Insight branding.
 *
 * Logo: drop the official asset at frontend/public/brand/insight-logo.svg (or .png and change logoUrl).
 * Until it exists the UI renders a text wordmark. Colours are approximations of the Insight palette;
 * replace them with the official brand-guide values here and in the :root block of styles.css.
 */
export const brand = {
  company: "Insight",
  product: "Domain Assessment Studio",
  tagline: "Industry-aware project assessments, from RFP to readiness.",
  logoUrl: "/brand/insight-logo.svg",
  colors: {
    primary: "#e3005a", // brand accent
    secondary: "#5a1e96", // gradient partner
    ink: "#14102b", // navigation / hero background
  },
};
