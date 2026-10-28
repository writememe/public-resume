const fs = require("node:fs/promises");
const path = require("node:path");
const puppeteer = require("puppeteer");
const theme = require("jsonresume-theme-stackoverflow");

const repositoryRoot = path.resolve(__dirname, "..");
const sourcePath = path.join(repositoryRoot, "resume.json");
const siteDirectory = path.join(repositoryRoot, "site");
const htmlPath = path.join(siteDirectory, "index.html");
const pdfPath = path.join(siteDirectory, "resume.pdf");
const jsonPath = path.join(siteDirectory, "resume.json");

async function buildSite() {
  const resume = JSON.parse(await fs.readFile(sourcePath, "utf8"));

  // This theme uses the legacy `company` field; JSON Resume stores it as `name`.
  resume.work = (resume.work || []).map((job) => ({
    ...job,
    company: job.name,
  }));

  const html = theme.render(resume);
  await fs.mkdir(siteDirectory, { recursive: true });
  await fs.writeFile(htmlPath, html);
  await fs.copyFile(sourcePath, jsonPath);

  const browser = await puppeteer.launch({
    executablePath:
      process.env.PUPPETEER_EXECUTABLE_PATH || puppeteer.executablePath(),
  });

  try {
    const page = await browser.newPage();
    await page.emulateMediaType(
      (theme.pdfRenderOptions && theme.pdfRenderOptions.mediaType) || "screen",
    );
    await page.goto(
      `data:text/html;base64,${Buffer.from(html, "utf8").toString("base64")}`,
      { waitUntil: "networkidle0" },
    );
    await page.pdf({
      path: pdfPath,
      format: "Letter",
      printBackground: true,
      ...theme.pdfRenderOptions,
    });
  } finally {
    await browser.close();
  }

  console.log(`Generated ${path.relative(repositoryRoot, htmlPath)}`);
  console.log(`Generated ${path.relative(repositoryRoot, pdfPath)}`);
  console.log(`Copied ${path.relative(repositoryRoot, jsonPath)}`);
}

buildSite().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
