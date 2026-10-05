package io.github.halvar20000.bambulan;

// One MQTT connection to a Bambu printer (Eclipse Paho): subscribes to its reports, asks for the full state once
// ("pushall" - the P1 series sends only changes afterwards, and Bambu advises against asking for it often).

import java.nio.charset.StandardCharsets;

import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended;
import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.eclipse.paho.client.mqttv3.MqttException;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;

public final class BambuMqtt {
  public interface Listener {
    void message(String payload);
    void state(boolean connected, String error);
  }

  private final MqttClient client;
  private final String serial;

  public BambuMqtt(String host, String serial, String code, Listener listener) throws MqttException {
    this.serial = serial;
    String id = "pp3d-app-" + serial.substring(Math.max(0, serial.length() - 6)) + "-" + (System.currentTimeMillis() % 100000);
    client = new MqttClient("ssl://" + host + ":" + BambuCore.MQTT_PORT, id, new MemoryPersistence());
    MqttConnectOptions o = new MqttConnectOptions();
    o.setUserName(BambuCore.USER);
    o.setPassword(code.toCharArray());
    o.setSocketFactory(BambuCore.trustAll().getSocketFactory());
    o.setHttpsHostnameVerificationEnabled(false);
    o.setAutomaticReconnect(true);
    o.setCleanSession(true);
    o.setKeepAliveInterval(30);
    o.setConnectionTimeout(10);
    client.setCallback(new MqttCallbackExtended() {
      @Override public void connectComplete(boolean reconnect, String uri) {
        // not on Paho's callback thread: a blocking subscribe there waits for itself (no message ever arrives)
        Thread t = new Thread(() -> {
          try {
            client.subscribe("device/" + serial + "/report", 0);
            publish("{\"pushing\":{\"command\":\"pushall\"}}");
            publish("{\"info\":{\"command\":\"get_version\"}}");
            listener.state(true, null);
          } catch (MqttException e) {
            listener.state(false, e.getMessage());
          }
        }, "bambu-subscribe");
        t.setDaemon(true);
        t.start();
      }
      @Override public void connectionLost(Throwable cause) {
        listener.state(false, cause == null ? "connection lost" : cause.getMessage());
      }
      @Override public void messageArrived(String topic, MqttMessage message) {
        listener.message(new String(message.getPayload(), StandardCharsets.UTF_8));
      }
      @Override public void deliveryComplete(IMqttDeliveryToken token) {}
    });
    try {
      client.connect(o);
    } catch (MqttException e) {
      int reason = e.getReasonCode();
      if (reason == MqttException.REASON_CODE_FAILED_AUTHENTICATION || reason == MqttException.REASON_CODE_NOT_AUTHORIZED) {
        throw new MqttException(reason, new Exception("the printer refused the access code"));
      }
      throw e;
    }
  }

  /** `json` = {"print": {...}} etc.; a sequence_id is added by the caller or left out (the printer accepts both). */
  public synchronized void publish(String json) throws MqttException {
    client.publish("device/" + serial + "/request", json.getBytes(StandardCharsets.UTF_8), 0, false);
  }

  public boolean connected() {
    return client.isConnected();
  }

  public void close() {
    try {
      client.disconnectForcibly(1000, 1000);
      client.close();
    } catch (MqttException ignored) {
      // closing anyway
    }
  }
}
