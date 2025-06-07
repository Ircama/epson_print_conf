# Tagging

Push all changes:

```shell
git commit -a
git push
```

_After pushing the last commit_, add a local tag (shall be added AFTER the commit that needs to rebuild the exe):

```shell
git tag # list local tags
git tag v2.1.3
```

Push this tag to the origin, which starts the rebuild workflow (GitHub Action):

```shell
git push origin v2.1.3
git ls-remote --tags https://github.com/Ircama/epson_print_conf # list remote tags
```

Check the published tag here: https://github.com/Ircama/epson_print_conf/tags

It shall be even with the last commit.

Check the GitHub Action: https://github.com/Ircama/epson_print_conf/actions

# Updating the same tag (using a different build number for publishing)

```shell
git tag # list tags
git tag -d epson_print_conf # remove local tag
git push --delete origin epson_print_conf # remove remote tag
git ls-remote --tags https://github.com/Ircama/epson_print_conf # list remote tags
```

Then follow the tagging procedure again to add the tag to the latest commit.

# Pushing the docker container

```shell
sudo docker login
sudo docker buildx build --platform linux/amd64,linux/arm64 -t ircama/epson_print_conf --push .

sudo docker run --publish 5990:5990 ircama/epson_print_conf
```
