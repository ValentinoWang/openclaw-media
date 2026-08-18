ALTER TABLE media_document.resources
    DROP CONSTRAINT resources_file_name_check;

ALTER TABLE media_document.resources
    ADD CONSTRAINT resources_file_name_check CHECK (
        length(btrim(file_name)) BETWEEN 1 AND 255
        AND strpos(file_name, '/') = 0
        AND strpos(file_name, E'\\') = 0
        AND strpos(file_name, chr(13)) = 0
        AND strpos(file_name, chr(10)) = 0
    );
