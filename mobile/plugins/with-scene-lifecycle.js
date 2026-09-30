// Adopts the UIScene life cycle on iOS. Apps built with the iOS 27 SDK crash at launch
// (UIApplicationEvaluateRuntimeIssueForNoSceneLifecycleAdoption) without it, and the
// SDK 57 bare template doesn't wire it up yet. Mirrors what the Expo canary template does:
// SceneDelegate subclasses expo's ExpoAppSceneDelegate, which creates the window, starts
// React Native and forwards URL/user-activity events to the AppDelegate.
// Remove once the Expo template ships a SceneDelegate itself.
const fs = require('fs');
const path = require('path');
const {
  IOSConfig,
  withAppDelegate,
  withDangerousMod,
  withInfoPlist,
  withXcodeProject,
} = require('expo/config-plugins');

const SCENE_DELEGATE = `internal import Expo

@objc(SceneDelegate)
class SceneDelegate: ExpoAppSceneDelegate {
  // Extension point for config plugins.
}
`;

const withSceneManifest = (config) =>
  withInfoPlist(config, (config) => {
    config.modResults.UIApplicationSceneManifest = {
      UIApplicationSupportsMultipleScenes: false,
      UISceneConfigurations: {
        UIWindowSceneSessionRoleApplication: [
          {
            UISceneConfigurationName: 'Default Configuration',
            UISceneDelegateClassName: '$(PRODUCT_MODULE_NAME).SceneDelegate',
          },
        ],
      },
    };
    return config;
  });

const withSceneAppDelegate = (config) =>
  withAppDelegate(config, (config) => {
    if (config.modResults.language !== 'swift') {
      throw new Error('with-scene-lifecycle: expected a Swift AppDelegate');
    }
    let src = config.modResults.contents;
    if (src.includes('ExpoReactNativeFactoryProvider')) return config;

    src = src.replace(
      'class AppDelegate: ExpoAppDelegate {',
      'class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {'
    );
    // The scene delegate creates the window and starts React Native.
    src = src.replace(
      /#if os\(iOS\) \|\| os\(tvOS\)\n\s*window = UIWindow\(frame: UIScreen\.main\.bounds\)[\s\S]*?#endif\n/,
      ''
    );
    // UIKit no longer calls these under the scene life cycle; ExpoAppSceneDelegate
    // forwards URLs and user activities to RCTLinkingManager itself.
    src = src.replace(/\n  \/\/ Linking API\n[\s\S]*?\n  \/\/ Universal Links\n[\s\S]*?\n  }\n/, '\n');

    if (!src.includes('ExpoReactNativeFactoryProvider {') || src.includes('UIScreen.main.bounds')) {
      throw new Error('with-scene-lifecycle: AppDelegate template changed, update the plugin');
    }
    config.modResults.contents = src;
    return config;
  });

const withSceneDelegateFile = (config) =>
  withDangerousMod(config, [
    'ios',
    async (config) => {
      const projectName = IOSConfig.XcodeUtils.getProjectName(config.modRequest.projectRoot);
      const file = path.join(config.modRequest.platformProjectRoot, projectName, 'SceneDelegate.swift');
      fs.writeFileSync(file, SCENE_DELEGATE);
      return config;
    },
  ]);

const withSceneDelegateInProject = (config) =>
  withXcodeProject(config, (config) => {
    const project = config.modResults;
    const projectName = IOSConfig.XcodeUtils.getProjectName(config.modRequest.projectRoot);
    const filepath = `${projectName}/SceneDelegate.swift`;
    if (!project.hasFile(filepath)) {
      IOSConfig.XcodeUtils.addBuildSourceFileToGroup({
        filepath,
        groupName: projectName,
        project,
        // Not the first target: that may be the share extension.
        targetUuid: IOSConfig.Target.findNativeTargetByName(project, projectName)[0],
      });
    }
    return config;
  });

module.exports = (config) =>
  withSceneDelegateInProject(
    withSceneDelegateFile(withSceneAppDelegate(withSceneManifest(config)))
  );
