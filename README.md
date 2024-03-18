# Public Resume 

This repository contains a definition of my resume, which adheres to the [JSON Resume Schema](https://jsonresume.org/schema/)

## Pre-requistes

- Setup a Github Gist, so that the JSON resume can be published to the Gist.

The following is required if you plan to automate to use CI to auto-deploy the changes.

- [Optional] Create a personal access token which contains the `gist` scope.
- [Optional] Go to your repository settings, then to the secrets page, and add a new secret called `ACCESS_TOKEN` with the value being from the token you created in the step above.

## Resume Definition

The resume is defined in the [resume.json](./resume.json) file. 

## Hosted Resume

The resume can be viewed at any time at the following URL:  

[https://registry.jsonresume.org/writememe](https://registry.jsonresume.org/writememe)

NOTE: JSON Resume allows you to apply a "theme" to a resume. Below are some examples of the same resume, with a different theme applied:

 - [even theme](https://registry.jsonresume.org/writememe?theme=even)
 - [kendall theme](https://registry.jsonresume.org/writememe?theme=kendall)
 - [relaxed theme](https://registry.jsonresume.org/writememe?theme=relaxed)

For more information about themes, please consult the documentation here: 

[https://jsonresume.org/themes/](https://jsonresume.org/themes/)

## Automated CI Workflow

There is an automated CI workflow which performs the following:

- Validate the resume complies against the schema
- Updates the [Github Gist](https://gist.github.com/writememe/529bc4626305136609b1cc5b34d4654c), which is used as the source for the Hosted Resume, as per the [setup instructions](https://jsonresume.org/getting-started/)
- After that, the [Hosted Resume](https://registry.jsonresume.org/writememe) will show the changes

[CI Workflow](.github/workflows/update-gist.yaml)
