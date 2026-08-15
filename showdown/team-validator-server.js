'use strict';

const http = require('node:http');
const { Teams } = require('./dist/sim');
const { TeamValidator } = require('./dist/sim/team-validator');

const HOST = '0.0.0.0';
const PORT = Number(process.env.KOALABATTLE_TEAM_VALIDATOR_PORT || 8002);
const MAX_BODY_BYTES = 55_000;
const SUPPORTED_FORMAT = 'gen9ou';

function reply(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store'
  });
  response.end(body);
}

function validate(payload) {
  if (!payload || payload.format !== SUPPORTED_FORMAT || typeof payload.team !== 'string') {
    return { status: 422, body: { detail: `format must be ${SUPPORTED_FORMAT} and team must be text` } };
  }
  if (!payload.team || Buffer.byteLength(payload.team, 'utf8') > 50_000) {
    return { status: 413, body: { detail: 'team must be 1-50000 UTF-8 bytes' } };
  }
  const team = Teams.import(payload.team);
  const errors = TeamValidator.get(SUPPORTED_FORMAT).validateTeam(team) || [];
  if (errors.length) {
    return {
      status: 200,
      body: { schema_version: '1.0', format: SUPPORTED_FORMAT, valid: false, errors }
    };
  }
  return {
    status: 200,
    body: {
      schema_version: '1.0',
      format: SUPPORTED_FORMAT,
      valid: true,
      errors: [],
      normalized_export: Teams.export(team),
      packed_team: Teams.pack(team),
      structured_team: team
    }
  };
}

const server = http.createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/healthz') {
    reply(response, 200, { status: 'ok', format: SUPPORTED_FORMAT });
    return;
  }
  if (request.method !== 'POST' || request.url !== '/validate') {
    reply(response, 404, { detail: 'not found' });
    return;
  }
  const chunks = [];
  let size = 0;
  request.on('data', (chunk) => {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) request.destroy();
    else chunks.push(chunk);
  });
  request.on('end', () => {
    try {
      const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      const result = validate(payload);
      reply(response, result.status, result.body);
    } catch {
      reply(response, 400, { detail: 'invalid JSON' });
    }
  });
  request.on('error', () => {
    if (!response.headersSent) reply(response, 413, { detail: 'request body too large' });
  });
});

server.listen(PORT, HOST, () => {
  process.stdout.write(`KoalaBattle team validator listening on ${HOST}:${PORT}\n`);
});
