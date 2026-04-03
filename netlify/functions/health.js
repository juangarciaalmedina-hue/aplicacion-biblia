exports.handler = async function handler() {
  return {
    statusCode: 200,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ok: true,
      service: "biblia-app-netlify",
      timestamp: new Date().toISOString(),
    }),
  };
};
