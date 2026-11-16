/* Avisos en tiempo real para todas las páginas (usuario autenticado).
   Abre un WebSocket a /ws/notificaciones/ y mantiene:
   - el contador de mensajes no leídos del menú "Mensajes";
   - avisos emergentes de mensajes nuevos y de eventos recién publicados.
   Reenvía cada aviso como evento del DOM para que chat.js actualice la bandeja. */
(function () {
  'use strict';

  var host = document.getElementById('toasts');
  if (!host || !('WebSocket' in window)) { return; }

  var PLACEHOLDER = '00000000-0000-0000-0000-000000000000';
  var PING_MS = 25000;
  var MAX_FAILED_ATTEMPTS = 8;   // Sesión caducada o servidor caído: no insistir sin fin.
  var TOAST_MS = 6000;
  var MAX_TOASTS = 3;

  var badges = document.querySelectorAll('[data-unread-badge]');
  var scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
  var url = scheme + window.location.host + '/ws/notificaciones/';
  var socket = null;
  var pingTimer = null;
  var failedAttempts = 0;

  function setBadge(total) {
    badges.forEach(function (badge) {
      badge.textContent = total > 99 ? '99+' : String(total);
      badge.hidden = total <= 0;
      badge.setAttribute('aria-label', total + ' mensajes sin leer');
    });
  }

  function urlFor(template, id) {
    return template ? template.replace(PLACEHOLDER, encodeURIComponent(id)) : '#';
  }

  function toast(title, text, href) {
    var node = document.createElement(href ? 'a' : 'div');
    if (href) { node.href = href; }
    node.className = 'toast';
    var strong = document.createElement('strong');
    strong.textContent = title;            // textContent: nunca se interpreta como HTML.
    var span = document.createElement('span');
    span.textContent = text;
    node.appendChild(strong);
    node.appendChild(span);
    host.appendChild(node);
    while (host.children.length > MAX_TOASTS) { host.removeChild(host.firstChild); }
    window.setTimeout(function () {
      if (node.parentNode) { node.parentNode.removeChild(node); }
    }, TOAST_MS);
  }

  function emit(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail: detail }));
  }

  function handle(data) {
    if (data.type === 'unread') {
      setBadge(data.unread_total);
      emit('agora:unread', data);
    } else if (data.type === 'chat') {
      setBadge(data.unread_total);
      emit('agora:chat-notify', data);
      toast(
        data.sender_name + (data.is_general ? ' · Sala general' : ''),
        data.event_name + ': ' + data.preview,
        urlFor(host.dataset.conversationUrl, data.conversation_id)
      );
    } else if (data.type === 'event') {
      toast(
        'Nuevo evento en cartelera',
        data.name + (data.start_date ? ' · ' + data.start_date : ''),
        urlFor(host.dataset.eventUrl, data.event_id)
      );
    }
  }

  function connect() {
    var opened = false;
    socket = new WebSocket(url);

    socket.onopen = function () {
      opened = true;
      failedAttempts = 0;
      pingTimer = window.setInterval(function () {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'ping' }));
        }
      }, PING_MS);
    };

    socket.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (error) { return; }
      if (data && typeof data === 'object') { handle(data); }
    };

    socket.onclose = function (event) {
      window.clearInterval(pingTimer);
      // 4401: el servidor cerró la sesión (cuenta suspendida). No reconectar.
      if (event.code === 4401) { return; }
      if (!opened) { failedAttempts += 1; }
      if (failedAttempts >= MAX_FAILED_ATTEMPTS) { return; }
      var delay = Math.min(30000, 1000 * Math.pow(2, failedAttempts));
      window.setTimeout(connect, delay);
    };
  }

  connect();
}());
