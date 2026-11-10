self.addEventListener('push', event => {
  let message = {};
  if (event.data) {
    try {
      message = event.data.json();
    } catch {
      message = {body: event.data.text()};
    }
  }

  const title = message.title || 'Life Inbox';
  const options = {
    body: message.body || 'You have tasks to review.',
    tag: message.tag || 'life-inbox-notification',
    data: {url: message.url || '/'}
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(
    event.notification.data?.url || '/',
    self.location.origin
  );
  if (target.origin !== self.location.origin) {
    target.pathname = '/';
    target.search = '';
    target.hash = '';
  }

  event.waitUntil(
    self.clients.matchAll({type: 'window', includeUncontrolled: true})
      .then(clients => {
        for (const client of clients) {
          if ('focus' in client) {
            client.navigate(target.href);
            return client.focus();
          }
        }
        return self.clients.openWindow(target.href);
      })
  );
});
