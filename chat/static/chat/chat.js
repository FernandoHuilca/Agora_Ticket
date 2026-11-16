/* Página "Mensajes".
   1) Mantiene la lista de conversaciones al día con los avisos de notifications.js.
   2) Si hay una conversación abierta, la conecta por WebSocket: mensajes en vivo,
      usuarios conectados, "escribiendo…", historial paginado y reconexión.
   Todo texto de usuarios se inserta con textContent (nunca innerHTML) para evitar XSS. */
(function () {
  'use strict';

  var PLACEHOLDER = '00000000-0000-0000-0000-000000000000';
  var list = document.getElementById('chat-list');
  var itemTemplate = document.getElementById('chat-item-template');

  // ---------- 1) Lista de conversaciones ----------

  function findItem(conversationId) {
    return list ? list.querySelector('[data-conversation-id="' + conversationId + '"]') : null;
  }

  function setItemUnread(item, count) {
    var badge = item.querySelector('[data-unread]');
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.hidden = count <= 0;
  }

  function touchItem(item, previewText) {
    item.querySelector('[data-preview]').textContent = previewText;
    var row = item.closest('li');
    if (row && list.firstElementChild !== row) { list.insertBefore(row, list.firstElementChild); }
  }

  function createItem(data) {
    // Conversación nueva para el organizador: aún no estaba en la lista.
    var fragment = itemTemplate.content.cloneNode(true);
    var item = fragment.querySelector('[data-conversation-id]');
    item.dataset.conversationId = data.conversation_id;
    item.href = list.dataset.conversationUrl.replace(PLACEHOLDER, data.conversation_id);
    item.querySelector('[data-avatar]').textContent = data.is_general ? '#' : data.sender_name.charAt(0);
    item.querySelector('[data-title]').textContent = data.is_general ? 'Sala general' : data.sender_name;
    item.querySelector('[data-subtitle]').textContent = data.event_name;
    var empty = list.querySelector('[data-empty]');
    if (empty) { empty.remove(); }
    list.insertBefore(fragment, list.firstElementChild);
    return findItem(data.conversation_id);
  }

  if (list) {
    document.addEventListener('agora:chat-notify', function (event) {
      var data = event.detail;
      var item = findItem(data.conversation_id) || createItem(data);
      touchItem(item, data.sender_name + ': ' + data.preview);
      setItemUnread(item, data.conversation_unread);
    });

    document.addEventListener('agora:unread', function (event) {
      var counts = event.detail.by_conversation || {};
      list.querySelectorAll('[data-conversation-id]').forEach(function (item) {
        setItemUnread(item, counts[item.dataset.conversationId] || 0);
      });
    });
  }

  // ---------- 2) Conversación abierta ----------

  var configNode = document.getElementById('chat-config');
  if (!configNode) { return; }
  var config = JSON.parse(configNode.textContent);

  var PING_MS = 25000;
  var TYPING_SEND_MS = 2500;
  var TYPING_SHOW_MS = 3500;
  var MAX_FAILED_ATTEMPTS = 8;

  var scroller = document.getElementById('chat-messages');
  var thread = document.getElementById('chat-thread');
  var olderButton = document.getElementById('chat-older');
  var emptyNote = document.getElementById('chat-empty-note');
  var statusNode = document.getElementById('chat-status');
  var presenceNode = document.getElementById('chat-presence');
  var typingNode = document.getElementById('chat-typing');
  var form = document.getElementById('chat-form');
  var input = document.getElementById('chat-input');
  var sendButton = document.getElementById('chat-send');
  var counter = document.getElementById('chat-counter');
  var errorNode = document.getElementById('chat-error');

  var messages = config.messages.slice();   // Siempre en orden cronológico.
  var hasMore = config.hasMore;
  var socket = null;
  var pingTimer = null;
  var typingTimer = null;
  var lastTypingSent = 0;
  var failedAttempts = 0;
  var everConnected = false;
  var stopped = false;

  var timeFormat = new Intl.DateTimeFormat('es', { hour: '2-digit', minute: '2-digit' });
  var dayFormat = new Intl.DateTimeFormat('es', { weekday: 'long', day: 'numeric', month: 'long' });

  function dayKey(date) {
    return date.getFullYear() + '-' + date.getMonth() + '-' + date.getDate();
  }

  function dayLabel(date) {
    var today = new Date();
    var yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    if (dayKey(date) === dayKey(today)) { return 'Hoy'; }
    if (dayKey(date) === dayKey(yesterday)) { return 'Ayer'; }
    return dayFormat.format(date);
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  function buildMessage(message) {
    var mine = message.sender_id === config.userId;
    var row = element('div', 'chat-msg' + (mine ? ' mine' : ''));
    row.dataset.messageId = message.id;
    var bubble = element('div', 'chat-bubble');
    if (!mine) {
      var author = element('div', 'chat-author', message.sender_name);
      if (message.is_organizer) { author.appendChild(element('span', 'badge', 'Organizador')); }
      bubble.appendChild(author);
    }
    bubble.appendChild(element('div', 'chat-text', message.body));
    var date = new Date(message.created_at);
    var time = element('time', 'chat-time', timeFormat.format(date));
    time.dateTime = message.created_at;
    bubble.appendChild(time);
    row.appendChild(bubble);
    return row;
  }

  function appendWithDay(container, message, previous) {
    var date = new Date(message.created_at);
    if (!previous || dayKey(new Date(previous.created_at)) !== dayKey(date)) {
      container.appendChild(element('div', 'chat-day', dayLabel(date)));
    }
    container.appendChild(buildMessage(message));
  }

  function renderAll() {
    var fragment = document.createDocumentFragment();
    messages.forEach(function (message, index) {
      appendWithDay(fragment, message, messages[index - 1]);
    });
    thread.replaceChildren(fragment);
    olderButton.hidden = !hasMore;
    emptyNote.hidden = messages.length > 0;
  }

  function nearBottom() {
    return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  }

  function scrollToBottom() {
    scroller.scrollTop = scroller.scrollHeight;
  }

  function updateOwnItem(message) {
    var item = findItem(config.conversationId);
    if (!item) { return; }
    var mine = message.sender_id === config.userId;
    var text = message.body.replace(/\s+/g, ' ');
    touchItem(item, (mine ? 'Tú' : message.sender_name) + ': ' + text.slice(0, 90));
  }

  function addMessage(message) {
    if (messages.some(function (known) { return known.id === message.id; })) { return; }
    var stick = nearBottom() || message.sender_id === config.userId;
    appendWithDay(thread, message, messages[messages.length - 1]);
    messages.push(message);
    emptyNote.hidden = true;
    if (stick) { scrollToBottom(); }
    updateOwnItem(message);
  }

  function fetchHistory(query) {
    return fetch(config.historyUrl + query, {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    }).then(function (response) {
      if (!response.ok) { throw new Error('history ' + response.status); }
      return response.json();
    });
  }

  olderButton.addEventListener('click', function () {
    if (!messages.length) { return; }
    olderButton.disabled = true;
    var previousHeight = scroller.scrollHeight;
    fetchHistory('?before=' + messages[0].id).then(function (data) {
      messages = data.messages.concat(messages);
      hasMore = data.has_more;
      renderAll();
      // Conserva la posición de lectura al insertar mensajes arriba.
      scroller.scrollTop += scroller.scrollHeight - previousHeight;
    }).catch(function () {
      showError('No se pudo cargar el historial. Inténtalo de nuevo.');
    }).finally(function () {
      olderButton.disabled = false;
    });
  });

  function recoverMissed() {
    // Tras una reconexión se piden los mensajes posteriores al último recibido.
    var last = messages.length ? messages[messages.length - 1].id : 0;
    fetchHistory('?after=' + last).then(function (data) {
      data.messages.forEach(addMessage);
    }).catch(function () { /* Se reintentará en la próxima reconexión. */ });
  }

  function setStatus(state, text) {
    statusNode.dataset.state = state;
    statusNode.textContent = text;
    if (sendButton) { sendButton.disabled = state !== 'online' || !input.value.trim(); }
  }

  function showError(text) {
    if (errorNode) { errorNode.textContent = text; }
  }

  function renderPresence(users) {
    presenceNode.replaceChildren();
    var others = users.filter(function (user) { return user.id !== config.userId; });
    var label = users.length === 1 ? '1 conectado' : users.length + ' conectados';
    presenceNode.appendChild(element('span', 'chat-dot'));
    var names = others.map(function (user) {
      return user.role === 'buyer' ? user.name : user.name + ' (' + user.role_label + ')';
    });
    names.unshift('Tú');
    presenceNode.appendChild(element('span', '', label + ': ' + names.join(', ')));
  }

  function showTyping(name) {
    typingNode.textContent = name + ' está escribiendo…';
    window.clearTimeout(typingTimer);
    typingTimer = window.setTimeout(function () { typingNode.textContent = ''; }, TYPING_SHOW_MS);
  }

  function send(payload) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }

  function handle(data) {
    if (data.type === 'message') {
      typingNode.textContent = '';
      addMessage(data);
    } else if (data.type === 'presence') {
      renderPresence(data.users);
    } else if (data.type === 'typing') {
      showTyping(data.name);
    } else if (data.type === 'error') {
      showError(data.message);
    }
  }

  function connect() {
    var opened = false;
    var scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    setStatus('connecting', everConnected ? 'Reconectando…' : 'Conectando…');
    socket = new WebSocket(scheme + window.location.host + config.socketPath);

    socket.onopen = function () {
      opened = true;
      failedAttempts = 0;
      setStatus('online', 'En línea');
      if (everConnected) { recoverMissed(); }
      everConnected = true;
      pingTimer = window.setInterval(function () { send({ type: 'ping' }); }, PING_MS);
    };

    socket.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (error) { return; }
      if (data && typeof data === 'object') { handle(data); }
    };

    socket.onclose = function (event) {
      window.clearInterval(pingTimer);
      presenceNode.replaceChildren();
      if (stopped) { return; }
      if (event.code === 4401 || event.code === 4403) {
        setStatus('offline', 'Sin acceso');
        showError('Tu sesión terminó o ya no tienes acceso a esta conversación.');
        return;
      }
      if (!opened) { failedAttempts += 1; }
      if (failedAttempts >= MAX_FAILED_ATTEMPTS) {
        setStatus('offline', 'Sin conexión');
        showError('No se pudo conectar con el chat. Recarga la página para reintentar.');
        return;
      }
      setStatus('connecting', 'Reconectando…');
      window.setTimeout(connect, Math.min(30000, 1000 * Math.pow(2, failedAttempts)));
    };
  }

  window.addEventListener('pagehide', function () {
    stopped = true;
    if (socket) { socket.close(); }
  });

  // ---------- Formulario de envío (validación en el cliente) ----------

  if (form) {
    var refreshForm = function () {
      var length = input.value.length;
      counter.textContent = length + '/' + config.maxLength;
      counter.classList.toggle('limit', length >= config.maxLength);
      sendButton.disabled = statusNode.dataset.state !== 'online' || !input.value.trim();
      // El cuadro de texto crece con el contenido hasta un máximo.
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 140) + 'px';
    };

    var submit = function () {
      var body = input.value.trim();
      if (!body) { showError('Escribe un mensaje antes de enviarlo.'); return; }
      if (body.length > config.maxLength) {
        showError('El mensaje no puede superar los ' + config.maxLength + ' caracteres.');
        return;
      }
      if (!send({ type: 'message', body: body })) {
        showError('Sin conexión. Espera a que el chat se reconecte.');
        return;
      }
      showError('');
      input.value = '';
      refreshForm();
      input.focus();
    };

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      submit();
    });

    input.addEventListener('keydown', function (event) {
      // Enter envía; Shift+Enter inserta un salto de línea.
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        submit();
      }
    });

    input.addEventListener('input', function () {
      refreshForm();
      var now = Date.now();
      if (input.value.trim() && now - lastTypingSent > TYPING_SEND_MS) {
        lastTypingSent = now;
        send({ type: 'typing' });
      }
    });

    refreshForm();
  }

  renderAll();
  scrollToBottom();
  connect();
}());
